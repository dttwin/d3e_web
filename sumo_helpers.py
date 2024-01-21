import sumolib
import math
from collections import defaultdict


class DetectorInfo:

    def __init__(self, sumo_net, detector_id, lane_id, pos):
        self.id = detector_id
        self.lane_id = lane_id
        self.pos = 0.0 if pos is None else float(pos)
        # Map the lane to the edge using `sumo_net`
        self.lane_object = sumo_net.getLane(lane_id)
        self.edge_object = self.lane_object.getEdge()
        self.edge_id = self.edge_object.getID()
        # These need to be instantiated later
        self.table_name = None
        self.column_prefix = None

    def set_table_and_column(self, tbl_name, col_pfx):
        self.table_name = tbl_name
        self.column_prefix = col_pfx

    def __str__(self):
        return f"DetectorInfo(id='{self.id}',table='{self.table_name}',column='{self.column_prefix}')"


class SumoDetectorMapper:

    def __init__(self, app):
        """

        :param app: Flask application
        :type app: Flask
        :return:
        """
        self.edge_map = defaultdict(list)
        self.detector_list = list()
        self.sumo_net = app.net
        e1_detectors = sumolib.xml.parse_fast('evropska.ext.det.add.xml', 'inductionLoop',
                                              ['id', 'lane', 'pos', 'vTypes'], optional=True)
        e2_detectors = sumolib.xml.parse_fast('evropska.ext.det.add.xml', 'laneAreaDetector',
                                              ['id', 'lane', 'pos', 'vTypes'], optional=True)
        detectors = list(e1_detectors) + list(e2_detectors)
        for det in detectors:
            det_info = DetectorInfo(app.net, det.id, det.lane, det.pos)
            # Process detector id
            id_split = det.id.split('_')
            # Only detectors whose names begin with 'DV*' will be processed
            if len(id_split) == 2:
                iid_full, det_full = id_split
                if det_full[:2] == 'DV':
                    assert(iid_full[1] == '.')
                    iid = 'SCALA.FD' + iid_full[0] + iid_full[2:]
                    db_detectors = app.db_scala.get_detectors(iid)
                    if db_detectors is None:
                        app.logger.warn(f"No detectors for intersection {iid_full}, ignoring detector {det_full}")
                        continue
                    det_split = det_full.split('.')
                    det_name = det_split[0]
                    det_name = det_name.replace("`", "'")
                    if len(det_split) == 1:
                        det_pos = 0
                    elif len(det_split) == 2:
                        det_pos = int(det_split[1])
                    else:
                        raise ValueError(f"Unexpected detector name format for '{det.id}'")
                    got_det = False
                    db_det_name = None
                    for db_det_name in db_detectors.keys():
                        if db_det_name.endswith(det_name):
                            got_det = True
                            break
                    if got_det:
                        det_info.set_table_and_column(iid, db_det_name)
                    else:
                        raise ValueError(f"Database for intersection {iid_full} does not contain detector '{det_name}'."
                                         f" Known detectors are {list(sorted(db_detectors.keys()))}.")
                    self.edge_map[det_info.edge_id].append(det_info)
                    self.detector_list.append(det_info)

    def calculate_distance(self, edge_object, detector_info):
        """
        Calculate distance from an edge to a detector

        """
        if edge_object.getID() == detector_info.edge_object.getID():
            # If the detector is on the same edge, just calculate the distance along the edge
            return abs(edge_object.getLength() - detector_info.pos)
        else:
            # Calculate the shortest path distance between edges
            try:
                route, route_length = self.sumo_net.getShortestPath(edge_object, detector_info.edge_object)
                if route is not None:
                    # Add the distance to the detector position on the detector edge
                    return route_length + detector_info.pos
            except Exception as e:
                print(f"Error finding path from `{edge_object.getID()}` to {detector_info.edge_id}: {e}")

        return math.inf

    def find_closest_detector(self, edge_id):
        """
        Find the closest detector to the given edge_id considering the position of the detector on its edge.
        TODO: We are ignoring edge position at the moment!

        :param edge_id: String with identifier of the edge
        :type edge_id: str
        :return: Tuple containing information about the closes detector and the distance.
        :rtype: tuple(DetectorInfo, float)
        """
        shortest_distance = math.inf
        closest_detector = None

        edge = self.sumo_net.getEdge(edge_id)
        for detector_info in self.detector_list:
            # Calculate the total distance from the current edge to the detector
            distance = self.calculate_distance(edge, detector_info)
            if distance < shortest_distance:
                print(f"For edge `{edge_id}` found closer detector `{detector_info}` in {distance}")
                shortest_distance = distance
                closest_detector = detector_info

        return closest_detector, shortest_distance


def load_network(network_file):
    """Loads the SUMO network using sumolib"""
    net = sumolib.net.readNet(network_file)
    return net
