import datetime
import random
import logging
from collections import defaultdict

# Try to import MariaDB or MySQL connectors
try:
    import mariadb as db
except ModuleNotFoundError:
    import mysql.connector as db

D3E_INTERSECTIONS = ['6120', '6138', '6118', '6131', '6158', '6157', '6115']


class ScalaDetectorDescriptor:

    def __init__(self, cnt=None, spd=None, occ=None, time_from=None, time_to=None):
        self.occ = occ
        self.spd = spd
        self.cnt = cnt
        self.start = time_from
        self.stop = time_to


class DatabaseError(Exception):
    pass


class ScalaDatabaseConnection:
    """
    Singleton class for database connection
    """
    _instance = None  # No instance at the beginning

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # And connect to the database
            cnx = db.connect(user='d3e', password='bP6FgDFNcxXJ', database='d3e')
            # Try to reconnect after a timeout
            cnx.auto_reconnect = True
            # Get all the tables from the server
            d3e_tables = list()
            # Get all descriptors
            data_map = defaultdict(lambda: defaultdict(ScalaDetectorDescriptor))
            cursor = cnx.cursor()
            cursor.execute("SHOW TABLES")
            table_list = cursor.fetchall()
            for table_row in table_list:
                table_name = table_row[0]
                if any(iid in table_name for iid in D3E_INTERSECTIONS):
                    d3e_tables.append(table_name)
                cursor.execute(f'SHOW COLUMNS FROM `{table_name}`')
                column_list = cursor.fetchall()
                idx = 0
                for column_row in column_list:
                    column_name = column_row[0]
                    det_split = column_name.split('.')
                    if len(det_split) == 2:
                        det_name, det_ext = det_split
                        if det_ext == 'cnt':
                            data_map[table_name][det_name].cnt = idx
                        elif det_ext == 'spd':
                            data_map[table_name][det_name].spd = idx
                        elif det_ext == 'occ':
                            data_map[table_name][det_name].occ = idx
                        elif det_ext == 'start':
                            data_map[table_name][det_name].start = idx
                        elif det_ext == 'stop':
                            data_map[table_name][det_name].stop = idx
                    idx += 1
            # Remember data map as an instance variable
            cls._instance.data_map = data_map
            cls._instance.d3e_tables = d3e_tables
            # Remember connection as an instance variable
            cls._instance.cnx = cnx
        return cls._instance

    def cursor(self):
        return self.cnx.cursor()

    def cnx(self):
        return self.cnx

    def execute_query(self, sql_query):
        try:
            cursor = self.cnx.cursor()
            cursor.execute(sql_query)
            res = cursor.fetchall()
            cursor.close()
            # This should prevent caching the SELECT results
            self.cnx.commit()
            return res
        except db.ProgrammingError as e:
            raise DatabaseError(e)

    def get_detectors(self, iid):
        if iid in self.data_map:
            return self.data_map[iid]
        return None

    def get_detector_for_edge(self, edge_id):
        import random
        table_id = random.choice(self.d3e_tables)
        dets = [d for d in self.data_map[table_id].keys() if '_DV' in d]
        detector = random.choice(dets)
        return table_id, detector

    def fetch_last_update(self):
        cursor = self.cnx.cursor()
        cursor.execute("SELECT value FROM `SCALA.status` WHERE `key`='last_update'")
        result = cursor.fetchone()
        last_update_str = result[0]
        return datetime.datetime.fromisoformat(last_update_str)

    def get_lag(self):
        lag = random.uniform(2.9, 3.6)
        return lag

    def get_capacity(self):
        return 89


class CameaDatabaseConnection:
    """
    Singleton class for database connection to CAMEA sensors
    """
    _instance = None  # No instance at the beginning
    _detector_types = ['bluetooth', 'det', 'rdet']  # Types of Camea detectors. Identical to DB table names.

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # And connect to the database
            cnx = db.connect(user='d3e', password='bP6FgDFNcxXJ', database='d3e_camea')
            # Get the names of all sensor ids for all three modalities that we are collecting
            detector_list = dict()
            cursor = cnx.cursor()
            for table_name in cls._detector_types:
                cursor.execute(f'SELECT DISTINCT `sensor_id` FROM `{table_name}`')
                sensor_list = sorted([c[0] for c in cursor.fetchall()])
                detector_list[table_name] = sensor_list
            # Remember connection as an instance variable
            cls._instance.cnx = cnx
            # Remember the detector list
            cls._instance.detector_list = detector_list
        return cls._instance

    def cursor(self):
        return self.cnx.cursor()

    def cnx(self):
        return self.cnx

    def execute_query(self, sql_query):
        try:
            cursor = self.cnx.cursor()
            cursor.execute(sql_query)
            res = cursor.fetchall()
            cursor.close()
            # This should prevent caching the SELECT results
            self.cnx.commit()
            return res
        except db.ProgrammingError as e:
            raise DatabaseError(e)

    def get_detector_types(self):
        return self._detector_types

    def get_detectors(self, type_id):
        return self.detector_list[type_id]
