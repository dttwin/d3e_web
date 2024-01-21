import datetime
import os

import sumolib
import pyproj
import rtree
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, current_user, logout_user, login_required
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
import folium
import requests
import time
import random
from datetime import datetime, timedelta
from forms import RegistrationForm, LoginForm, User

import sumo_helpers
from dbconnector import ScalaDatabaseConnection, CameaDatabaseConnection

# Configuration file
CONFIG_FILE = 'config.json'

DATA_BUFFER = dict()
EDGE_DETECTOR_MAP = dict()

# GLOBAL_TIMEDELTA = datetime.now() - datetime.fromisoformat('2024-05-12 13:44:27')
GLOBAL_TIMEDELTA = timedelta(minutes=1)

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SECRET_KEY'] = os.urandom(32)  # CSRF secret key

# Global login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Our own elements
app.db_scala = ScalaDatabaseConnection()
app.db_camea = CameaDatabaseConnection()
app.net = sumolib.net.readNet('evropska.net.xml')
app.detectors = sumo_helpers.SumoDetectorMapper(app)

# Our globals
last_update_time = None
last_scala_update_time = None


# Mock external traffic data source
def get_traffic_info(street_name):
    # In a real application, you would fetch this data from an external API
    # Here, we are returning a mock response
    traffic_data = {
        "Main St": "Heavy traffic due to construction.",
        "2nd Ave": "Clear.",
        "Broadway": "Moderate traffic.",
    }
    return traffic_data.get(street_name, "No data available.")


@login_manager.user_loader
def load_user(user_id):
    print(f'Getting user {user_id} ...')
    # return User.query.get(int(user_id))
    return None


@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for(''))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        #db.session.add(user)
        #db.session.commit()
        flash('Your account has been created! You can now log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = LoginForm()
    if form.validate_on_submit():
        # user = User.query.filter_by(email=form.email.data).first()
        user = False
        if user:  # and user.check_password(form.password.data):
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Login Unsuccessful. Please check email and password', 'danger')
    return render_template('login.html', form=form)

@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for('home'))


@app.route('/')
def index():
    start_coords = (50.0963026894525, 14.350053937447234)  # Coordinates for Nádraží Veleslavín
    folium_map = folium.Map(location=start_coords, zoom_start=18)

    folium.TileLayer('openstreetmap').add_to(folium_map)

    folium_map.get_root().render()
    header = folium_map.get_root().header.render()
    body_html = folium_map.get_root().html.render()
    script = folium_map.get_root().script.render()

    return render_template('index.html',
                           map_header=header, map_body=body_html, map_script=script, map_name=folium_map.get_name())


@app.route('/status')
def status():
    lag = app.db_scala.get_lag()
    capacity = app.db_scala.get_capacity()
    return render_template('status.html',
                           average_lag=lag, db_capacity=capacity)

@app.route('/about')
def about():

    return render_template('about.html')


@app.route('/get-chart', methods=['POST'])
def traffic_chart():
    data = request.json
    lat = data.get('lat')
    lng = data.get('lng')

    # Fetch data based on coordinates from external data sources
    info = f"Information for location ({lat:8.5f}, {lng:8.5f})"

    # Look for edges in a small radius around the given point
    radius = 5
    x, y = app.net.convertLonLat2XY(lng, lat)
    edges = app.net.getNeighboringEdges(x, y, radius)
    # Pick the closest edge
    if len(edges) > 0:
        distances_and_edges = sorted([(dist, edge) for edge, dist in edges], key=lambda x: x[0])
        dist, closest_edge = distances_and_edges[0]

        loc_id = f'{closest_edge.getID()}'
        # Get the corresponding table and detector(s) name(s)
        if loc_id in EDGE_DETECTOR_MAP:
            tbl, det_id = EDGE_DETECTOR_MAP[loc_id]
        else:
            detector_info, _ = app.detectors.find_closest_detector(loc_id)
            tbl = detector_info.table_name
            det_id = detector_info.column_prefix
            EDGE_DETECTOR_MAP[loc_id] = (tbl, det_id)
        # Provide additional info
        info += f" model edge {loc_id}, detector {tbl}/{det_id}"
        # Get the last 10 records for the edge
        result_set = app.db_scala.execute_query(f'SELECT `{det_id}.start`,`{det_id}.cnt` FROM `{tbl}` ORDER BY id DESC LIMIT 10')
        data = []
        sample_time = None
        for row in reversed(result_set):
            sample_time = row[0]
            data_tuple = (sample_time.isoformat(), row[1])
            data.append(data_tuple)
        DATA_BUFFER[loc_id] = (data, sample_time)

        # timestamps = [row[0].strftime("%Y-%m-%d %H:%M:%S") for row in data]
        timestamps = [row[0] for row in data]
        values = [row[1] for row in data]

    else:
        info += '<br/><strong>Warning:</strong>This location is not modelled'
        loc_id = None
        timestamps = []
        values = []

    return jsonify({"info": info, 'loc_id': loc_id, 'timestamps': timestamps, 'values': values})


@app.route('/get-chart-update', methods=['POST'])
def traffic_chart_update():
    data = request.json
    loc_id = data.get('loc_id')

    if loc_id not in DATA_BUFFER:
        return jsonify({'loc_id': f'Location {loc_id} is gone.', 'timestamps': None, 'values': None})

    # If in data buffer, it is also here
    tbl, det_id = EDGE_DETECTOR_MAP[loc_id]
    data, last_timestamp = DATA_BUFFER[loc_id]
    # Get the new records for the edge
    result_set = app.db_scala.execute_query(
        f"SELECT `{det_id}.start`,`{det_id}.cnt` FROM `{tbl}` WHERE `{det_id}.start`>'{last_timestamp}' ORDER BY id")
    sample_time = last_timestamp
    for row in result_set:
        sample_time = row[0]
        data_tuple = (sample_time.isoformat(), row[1])
        data.append(data_tuple)
    # Shorten the view to the last 15 entries
    if len(data) > 15:
        data = data[-15:]
    DATA_BUFFER[loc_id] = (data, sample_time)

    timestamps = [row[0] for row in data]
    values = [row[1] for row in data]

    return jsonify({'loc_id': loc_id, 'timestamps': timestamps, 'values': values})


@app.route('/get-last-update')
def last_update():
    global last_update_time
    global last_scala_update_time
    # Mock last update
    time_now = datetime.now()
    if last_update_time is None or time_now - last_update_time >= timedelta(seconds=10):
        last_scala_update_time = app.db_scala.fetch_last_update()
        last_update_time = time_now

    display_time = last_scala_update_time - GLOBAL_TIMEDELTA
    display_str = display_time.strftime("%Y-%m-%d %H:%M:%S")

    return jsonify({"last_update": display_str})


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False, host='0.0.0.0')
