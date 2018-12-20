from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.topology import switches
from ryu.topology import event
from ryu.topology import dhcps
from scipy import sparse
import time

from ryu.topology.short_path import get_all_short_path_sequence, INF


class Topo(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    # z指定该应用所需要的app实例
    _CONTEXTS = {
        'switches': switches.Switches,
        'dhcp': dhcps.DHCPResponder
    }
    _EVENTS = [event.EventTopoChange]

    def __init__(self, *args, **kwargs):
        super(Topo, self).__init__()
        self.switchMap = {}  # 记录所有交换机id对应在switches列表中的序号，便于对应查找交换机
        self.switches = []  # 记录所有的{switch},方便计算邻接矩阵
        self.links = {}  # 记录交换机之间的连接 {port1:port2,...} 最好这么记录
        self.host = {}  # 记录所有主机的信息 {mac:(dpid, port_no,ip)}

    @set_ev_cls(event.EventSwitchEnter)
    def switch_enter_handler(self, ev):
        sw = ev.switch
        self.switches.append(sw)
        self.switchMap[sw.dp.id] = len(self.switches) - 1
        print("switch " + str(sw.dp.id) + " enter")

    @set_ev_cls(event.EventSwitchLeave)
    def switch_leave_handler(self, ev):
        sw = ev.switch
        if sw in self.switches:
            self.switches.remove(sw)
            del self.switchMap[sw.dp.id]
            print("switch " + str(sw.dp.id) + " leave")

    @set_ev_cls(event.EventLinkAdd)
    def link_add_handler(self, ev):
        l = ev.link
        if l.src.dpid not in self.links:
            self.links[l.src] = l.dst
        self.send_event_to_observers(event.EventTopoChange('link add'))
        print("link s%d %d and s%d %d up" % (l.src.dpid, l.src.port_no, l.dst.dpid, l.dst.port_no))

    @set_ev_cls(event.EventLinkDelete)
    def link_del_handler(self, ev):
        l = ev.link
        if l.src in self.links:
            del self.links[l.src]
        self.send_event_to_observers(event.EventTopoChange('link delete'))
        print("link s%d %d and s%d %d down" % (l.src.dpid, l.src.port_no, l.dst.dpid, l.dst.port_no))

    @set_ev_cls(event.EventHostAdd)
    def Host_Add_Handler(self, ev):
        h = ev.host
        if h.mac not in self.host:
            self.host[h.mac] = (h.port.split(':')[0], h.port.split(':')[1], h.ipv4)
            self.send_event_to_observers(event.EventTopoChange('host add'))
            print("host %s %s add" % (h.mac, h.ipv4))

    @set_ev_cls(event.EventHostDelete)
    def Host_Delete_Handler(self, ev):
        h = ev.host
        if h.mac in self.host:
            self.host[h.mac] = (h.port.split(':')[0], h.port.split(':')[1], h.ipv4)
            del self.host[h.mac]
            self.send_event_to_observers(event.EventTopoChange('host delete'))
            print("host %s %s delete" % (h.mac, h.ipv4))

    def getAdjMatrix(self):
        if len(self.switches) == 0:
            return []
        r = sparse.dok_matrix((len(self.switches), len(self.switches)))
        for i in range(len(self.switches)):
            for j in range(len(self.switches)):
                if i != j:
                    for port1 in self.switches[i].ports:
                        for port2 in self.switches[j].ports:
                            if self.links.get(port1) and self.links[port1] == port2:
                                r[i, j] = 1
                                r[j, i] = 1
        return r.toarray()

    #判断；两个交换机是否相连，相连返回连接端口，不想连返回空
    def isConnect(self, sw1, sw2):
        assert isinstance(sw1, switches.Switch)
        assert isinstance(sw2, switches.Switch)
        for port1 in sw1.ports:
            for port2 in sw2.ports:
                if self.links.get(port1) and self.links[port1] == port2:
                    return (port1.dpid,port1.port_no, port2.dpid, port2.port_no)
        return None

    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst)
        print('send msg9999999999999999999')
        datapath.send_msg(mod)

    # 捕获拓扑改变的函数
    @set_ev_cls(event.EventTopoChange)
    def topoChangeHandler(self, ev):
        # print('==============getAdjMatrix=================')
        # print(self.getAdjMatrix())
        # print('===============switchMap==================')
        # print(self.switchMap)
        # print('=================host=====================')
        # print(self.host)
        # print('==================links====================')
        # for item in self.links:
        #     print('in_port: {0}, out_port: {1}'.format(item, self.links[item]))
        #     # print(item.__dict__)
        # print('===================links end======================')
        # a = self.isConnect(self.switches[0], self.switches[2])
        # if a is not None:
        #     print(a[0],a[1],a[2],a[3])
        # print(ev.msg)

        time.sleep(15)
        # self.add_flow_table_item()
        ip_port_dict = self.compute_path_between_all_hosts()

        # 每一个host2host，对其所经过路径上的所有交换机下发流表
        for item in ip_port_dict:
            # src_ip = item[0]
            # dst_ip = item[1]
            src_ip, dst_ip = item
            # print('146   items: {0}, src_ip: {1}, dst_ip: {2}'.format(item, src_ip, dst_ip))
            connection = ip_port_dict[item]
            path, ports, macs = connection
            src_mac, dst_mac = macs
            # print('path: {0}, ports: {1}, macs: {2}'.format(path, ports, macs))
            # print('src_mac: {0}, dst_mac: {1}'.format(src_mac, dst_mac))
            for i in range(len(path)):
                switch_dpid = path[i]
                # print('type of self.switchMap[switch_dpid]: {0}'.format(type(self.switchMap[switch_dpid])))
                print(self.switches[0].__dict__)
                datapath = self.switches[self.switchMap[switch_dpid]].dp
                ofproto = datapath.ofproto
                parser = datapath.ofproto_parser
                in_port = int(ports[i]['in_port'])
                # print('type of in_port: {0}, in_port: {1}'.format(type(in_port), in_port))
                out_port = int(ports[i]['out_port'])
                # print('switch_dpid: {0}'.format(switch_dpid))
                # print('in_port: {0}, out_port: {1}'.format(in_port, out_port))

                actions = [parser.OFPActionOutput(out_port)]        # 转发动作
                match = parser.OFPMatch(
                    ipv4_src=src_ip, ipv4_dst=dst_ip, eth_src=src_mac,
                    eth_dst=dst_mac,
                    in_port=in_port
                )
                self.add_flow(datapath, 1, match, actions)




    def index2switch_id(self, switch_index_seq):
        """
        把由交换机在交换机列表中的编号表示的路径序列转换为由交换机的编号表示的路径序列
        :param switch_index_seq: 由交换机在交换机列表中的编号表示的最短路径序列
        :return:由交换机编号表示的最短路径序列
        """
        path_seq = []
        index2switch = dict(zip(self.switchMap.values(), self.switchMap.keys()))
        for switch_index in switch_index_seq:
            switch_id = index2switch.get(switch_index)
            path_seq.append(switch_id)
        return path_seq

    def handle_matrix(self):
        """
        self.getAdjMatrix()返回的数据形如： [[0. 1. 0.], [1. 0. 1.], [0. 1. 0.]]
        把它转化为：[[0.e+00 1.e+00 1.e+04], [1.e+00 0.e+00 1.e+00], [1.e+04 1.e+00 0.e+00]]
        :return:
        """
        dis_matrix = self.getAdjMatrix()
        shape = self.getAdjMatrix().shape
        n_pathes = shape[0]
        # print('shape: {0}, n_pathes:{1}'.format(shape, n_pathes))
        for i in range(n_pathes):
            for j in range(n_pathes):
                if i != j and dis_matrix[i, j] == 0:
                    # print('before dis_matrix[{0},{1}]: {2}'.format(i, j, dis_matrix[i,j]))
                    dis_matrix[i, j] = INF
        # print('after handling: {0}'.format(dis_matrix))
        return dis_matrix

    def get_switch_id_path_sequence(self):
        """
        和我猜想的一样，那么需要将path_sequence中的switch列表中的编号转换成交换机的id
        switchMap中记录所有交换机id对应在switches列表中的序号，便于对应查找交换机
        获得网络中任意两个交换机结点之间的最短路径序列，路径序列由交换机编号来表示
        如:<1,3,4,7>表示从id为1的交换机到id为7的交换机的最短路径是从交换机1到交换机3到交换机4到交换机7
        :return:
        """
        n_switches = len(self.switches)
        dis_matrix = self.handle_matrix()

        # index_path_sequence中是以switch列表中的编号给出交换机之间的路径上的结点序列
        index_path_sequence = get_all_short_path_sequence(n_switches, dis_matrix)
        id_path_sequence = []
        for index_path in index_path_sequence:
            id_path = self.index2switch_id(index_path)
            id_path_sequence.append(id_path)
            # print('index_path: {0}'.format(index_path))
            # print('id_path: {0}'.format(id_path))
        return id_path_sequence

    def id_path_sequence2dict(self):
        """
        获取所有交换机（交换机由交换机的id来表示）的最短路径序列，并转化为字典
        如(0,4): [0,3,2,4] 键是表示路径的起点和终点，值是整个路径中经过的所有交换机结点组成的序列
        :return:
        """
        path_sequence = self.get_switch_id_path_sequence()   # 获得所有交换机的最短路径序列
        path_dict = {}
        for path in path_sequence:
            # 若path为空会发生什么
            if len(path) == 0:
                continue
            src_switch = path[0]
            dst_switch = path[-1]
            if src_switch != dst_switch:
                path_dict[(src_switch, dst_switch)] = path
        return path_dict

    def get_port0(self, src_switch, dst_switch, in_or_out):
        """
        输入两个主机，源交换机连接目的交换机的出端口
        in_or_out == 1: 求目的交换机的入端口；in_or_out == 2: 求源交换机的出端口
        :param src_switch:
        :param dst_switch:
        :return:
        """
        port = None
        for src_dpid, item in self.links.items():
            dst_dpid = item[1]
            if src_switch == src_dpid and dst_switch == dst_dpid:
                if in_or_out == 1:
                    port = item[2]
                else:
                    port = item[0]
                print('src_switch:{0}, dst_switch:{1}, port: {2}'.format(src_switch, dst_switch, port))
                return port
            elif src_switch == dst_dpid and dst_switch == src_dpid:
                if in_or_out == 1:
                    port = item[0]
                else:
                    port = item[2]
                print('src_switch:{0}, dst_switch:{1}, port: {2}'.format(src_switch, dst_switch, port))
                return port

    def port_maps(self):
        """
        通过link转换为交换机端口之间的连接关系
        :param src_switch:
        :param dst_switch:
        :param in_or_out:
        :return:
        """
        src_dst_port_map = dict()
        for src, dst in self.links.items():       # src,dst是Port对象
            src_dpid = src.dpid
            dst_dpid = dst.dpid
            src_port_no = src.port_no
            dst_port_no = dst.port_no
            # 将src_dpid作为源交换机，dst_dpid作为目的交换机，则src_port_no是源交换机的出端口，dst_port_no是目的交换机的入端口
            src_dst_port_map[(src_dpid, dst_dpid)] = (src_port_no, dst_port_no)
            src_dst_port_map[(dst_dpid, src_dpid)] = (dst_port_no, src_port_no)
        return src_dst_port_map

    def get_port(self, src_switch, dst_switch, in_or_out, src_dst_port_map):
        """
        输入两个主机，源交换机连接目的交换机的出端口
        in_or_out == 1: 求目的交换机的入端口；in_or_out == 2: 求源交换机的出端口
        :param src_switch:
        :param dst_switch:
        :param in_or_out:
        :param src_dst_port_map:
        :return:
        """
        # print('src_dst_port_map: {0}'.format(src_dst_port_map))
        if in_or_out == 1:
            return src_dst_port_map[(src_switch, dst_switch)][1]
        elif in_or_out == 2:
            return src_dst_port_map[(src_switch, dst_switch)][0]
        else:
            return None

    def get_ports_with_path(self, path, src_dst_port_map):
        """
        给定路径序列，返回这条路径上每个交换机对应的端口
        :param path:
        :return:
        """
        ports_list = []
        for i in range(len(path)):  # 将路径中的每个交换机转化为入端口和出端口
            # print('271 271 path: {0}'.format(path))
            port_dict = dict()
            if i == 0:              # 说明是连接源主机的那个交换机
                port_dict["in_port"] = "unknow"
                out_port = self.get_port(path[i], path[i + 1], 2, src_dst_port_map)
                port_dict["out_port"] = out_port
            elif i == len(path) - 1:  # 说明是连接目的主机的那个交换机
                in_port = self.get_port(path[i - 1], path[i], 1, src_dst_port_map)
                port_dict["in_port"] = in_port
                port_dict["out_port"] = "unknow"
            else:
                in_port = self.get_port(path[i - 1], path[i], 1, src_dst_port_map)
                out_port = self.get_port(path[i], path[i + 1], 2, src_dst_port_map)
                port_dict["in_port"] = in_port
                port_dict["out_port"] = out_port
            ports_list.append(port_dict)
        # print('path: {0}'.format(path))
        # print('ports_list: {0}'.format(ports_list))
        return ports_list

    def get_port_seq(self):
        """
        对网络中的任意两台交换机，计算出这两台交换机之间的结点交换机序列
        如<1,3,4,2>表示从交换机1到达交换机2需要经过交换机1,3,4,2，
        若1:1->3:1，3:2->4:2,4:1->2:2表示交换机1的端口1连接交换机3的端口1，交换机3的端口2连接交换机4的端口2，剩下以此类推
        则转换后的端口序列为：[{"i_port":"unknown","out_port":1},{"i_port":1,"out_port":2},{"i_port":2,"out_port":1},{"i_port":2,"out_port":"unknown"}]
        其中交换机1和交换机2分别连接源主机和目的主机，因此，in_port和out_port分别为unknown
        :return:
        """
        switch_ids = [id for id in self.switchMap.keys()]   # 获得所有交换机的id，即获取所有交换机
        path_dict = self.id_path_sequence2dict()
        src_dst_port_map = self.port_maps()
        print('src_dst_port_map: {0}'.format(src_dst_port_map))

        for src_id in switch_ids:
            for dst_id in switch_ids:
                if src_id != dst_id:    # 当源结点交换机和目的结点交换机不是同一个交换机时，将交换结点序列转换为入、出端口序列
                    path = path_dict[(src_id, dst_id)]  # 获得从源结点到目的结点的最短路径序列
                    ports_list = self.get_ports_with_path(path, src_dst_port_map)
                    path_dict[(src_id, dst_id)] = [path, ports_list]
        return path_dict

    def compute_path_between_all_hosts(self):
        """
        遍历网络中的所有IP对，返回每一对IP之间的最短路径上的交换机结点，以及每个结点的入端口和出端口
        :return:
        """
        ip_port_dict = {}
        path_dict = self.get_port_seq()     # path_dict[(src_id, dst_id)] = [path, ports_list]

        # 测试每条路径上的端口序列是否正确
        # for key, val in path_dict.items():
        #     if key[0] and key[1]:
        #         path = val[0]
        #         ports = val[1]
        #         # print('path: {0}, ports: {1}'.format(path, ports))
        # print('******************************************')

        # 对每一对IP,返回它们之间的最短路径上的交换机结点及每个结点的入端口和出端口

        for host_mac0, host_info0 in self.host.items():
            host_ip0 = host_info0[2]
            nearest_switch0 = host_info0[0]     # 注意：host_info0[0]是字符类型
            switch_port0 = host_info0[1]      # 连接交换机的端口
            for host_mac1, host_info1 in self.host.items():
                if host_mac0 == host_mac1:
                    continue
                host_ip1 = host_info1[2]
                nearest_switch1 = host_info1[0]
                switch_port1 = host_info1[1]
                nearest_switch0 = int(nearest_switch0)
                nearest_switch1 = int(nearest_switch1)
                mac_addr_dict = [host_mac0, host_mac1]
                if nearest_switch0 == nearest_switch1:      # 若两台主机连接着同一台交换机
                    path = [nearest_switch0, ]
                    ports = [{"in_port": switch_port0, "out_port": switch_port1}, ]
                    ip_port_dict[(host_ip0[0], host_ip1[0])] = [path, ports, mac_addr_dict]

                    # print('choice 111111111111111111')
                    # print('host_ip0: {0}, host_ip1: {1}'.format(host_ip0, host_ip1))
                    # print('path: {0}, ports: {1}'.format(path, ports))

                else:
                    path, ports = path_dict[(nearest_switch0, nearest_switch1)]             # path是个列表，ports是一个嵌套了字典的列表
                    # path, ports = path_dict[(nearest_switch0, nearest_switch1)]
                    ports[0]["in_port"] = switch_port0      # 入/出端口序列中的第一项的入端口连接着源主机的入端口
                    ports[-1]["out_port"] = switch_port1    # 入/出端口序列中的最后一项的出端口连接着目的主机的出端口
                    ip_port_dict[(host_ip0[0], host_ip1[0])] = [path, ports, mac_addr_dict]

                    # print('choice 2222222222')
                    # print('host_ip0: {0}, host_ip1: {1}'.format(host_ip0, host_ip1))
                    # print('path: {0}, ports: {1}'.format(path, ports))
        return ip_port_dict

    def add_flow_table_item(self):
        """
        最短路径计算完毕，下发流表项
        :return:
        """
        ip_port_dict = self.compute_path_between_all_hosts()
        # 打印出
        print('=*******************ip_port_dict********************=')
        for item in ip_port_dict:
            print('{0}: {1}'.format(item, ip_port_dict[item]))


