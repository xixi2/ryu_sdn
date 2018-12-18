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

    # 捕获拓扑改变的函数
    @set_ev_cls(event.EventTopoChange)
    def topoChangeHandler(self, ev):
        print(self.getAdjMatrix())
        print(self.switchMap)
        a = self.isConnect(self.switches[0], self.switches[2])
        if a is not None:
            print(a[0],a[1],a[2],a[3])
        print(ev.msg)
