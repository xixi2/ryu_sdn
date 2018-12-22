
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib import addrconv, hub
from ryu.lib.packet import dhcp, ethernet
from ryu.lib.packet import ipv4, packet, udp, arp
from ryu.ofproto import ofproto_v1_3
from ryu.topology import event
from ryu.topology import switches
import threading
import struct
import random
import time


class DHCPResponder(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _EVENTS = [
        event.EventHostAdd,
        event.EventHostDelete
    ]

    def __init__(self, *args, **kwargs):
        super(DHCPResponder, self).__init__(*args, **kwargs)
        self.name = 'dhcp'
        self.release_time = 30
        self.hw_addr = '0a:e4:1c:d1:3e:44'
        self.dhcp_server = '10.0.0.1'
        self.netmask = '255.0.0.0'
        self.dns = '8.8.8.8'
        self.bin_dns = addrconv.ipv4.text_to_bin(self.dns)
        self.hostname = 'dhcp'
        self.bin_netmask = addrconv.ipv4.text_to_bin(self.netmask)
        self.bin_server = addrconv.ipv4.text_to_bin(self.dhcp_server)
        self.ip_pool = {} #记录每个mac对应的ip，以及最近一次更新的时间
        self.ip_addr = '10.0.0.'
        self.usable_id = [i for i in range(2, 254)]
        self.mac_port = {} #记录每个mac对应的交换机端口以及交换机编号


    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # install table-miss flow entry
        #
        # We specify NO BUFFER to max_len of the output action due to
        # OVS bug. At this moment, if we specify a lesser number, e.g.,
        # 128, OVS will send Packet-In with invalid buffer_id and
        # truncated packet data. In that case, we cannot output packets
        # correctly.  The bug has been fixed in OVS v2.1.0.
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

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
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        pkt = packet.Packet(data=msg.data)
        pkt_udp = pkt.get_protocol(udp.udp)
        port = msg.match['in_port']
        pkt_arp = pkt.get_protocol(arp.arp)
        if pkt_arp:
            self.arp_handle(ev)
        if pkt_udp is None or udp.udp.get_packet_type(pkt_udp.src_port, pkt_udp.dst_port) != dhcp.dhcp:
            return
        if msg.msg_len < msg.total_len:
            # print("packet trucate %d of %d bytes" % (msg.msg_len, msg.total_len))
            #通过截断包可以知道对应主机对应端口
            actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER)]
            out = parser.OFPPacketOut(datapath=datapath,
                                      buffer_id=msg.buffer_id,
                                      in_port=ofproto.OFPP_CONTROLLER,
                                      actions=actions
                                      )
            self.mac_port[pkt.get_protocol(ethernet.ethernet).src] = [datapath.id, port]
            datapath.send_msg(out)
            return
        pkt = packet.Packet(data=msg.data)
        pkt_dhcp = pkt.get_protocol(dhcp.dhcp)
        smac = pkt.get_protocol(ethernet.ethernet).src
        port = self.mac_port[smac][1]
        if pkt_dhcp:
            self._handle_dhcp(datapath, port, pkt)

    def assemble_ack(self, pkt):
        #self.semaphore.acquire()
        #self.semaphore.release()
        req_eth = pkt.get_protocol(ethernet.ethernet)
        req_ipv4 = pkt.get_protocol(ipv4.ipv4)
        req_udp = pkt.get_protocol(udp.udp)
        req = pkt.get_protocol(dhcp.dhcp)
        req.options.option_list.remove(
            next(opt for opt in req.options.option_list if opt.tag == 53))
        req.options.option_list.insert(
            0, dhcp.option(tag=1, value=self.bin_netmask))
        req.options.option_list.insert(
            0, dhcp.option(tag=3, value=self.bin_server))
        req.options.option_list.insert(
            0, dhcp.option(tag=6, value=self.bin_dns))
        # disc.options.option_list.insert(
        #     0, dhcp.option(tag=12, value=self.hostname))
        req.options.option_list.insert(
            0, dhcp.option(tag=51, value=struct.pack('!I', self.release_time)))
        req.options.option_list.insert(
            0, dhcp.option(tag=53, value=struct.pack('!B', 5)))
        # disc.options.option_list.insert(
        #     0, dhcp.option(tag=54, value=self.hostname))
        req.options.option_list.insert(
            0, dhcp.option(tag=58, value=struct.pack('!I', self.release_time // 2)))
        req.options.option_list.insert(
            0, dhcp.option(tag=59, value=struct.pack('!I', self.release_time * 7 // 8)))
        if req_eth.src not in self.ip_pool:
            return
        # print(req_eth.src,end=" ")
        # print(self.ip_pool[req_eth.src][2], time.perf_counter())
        self.ip_pool[req_eth.src][1] = time.perf_counter()
        ack_pkt = packet.Packet()
        ack_pkt.add_protocol(ethernet.ethernet(
            ethertype=req_eth.ethertype, dst=req_eth.src, src=self.hw_addr))
        ack_pkt.add_protocol(
            ipv4.ipv4(dst=req_ipv4.dst, src=self.dhcp_server, proto=req_ipv4.proto))
        ack_pkt.add_protocol(udp.udp(src_port=67, dst_port=68))
        ack_pkt.add_protocol(dhcp.dhcp(op=2, chaddr=req_eth.src,
                                       siaddr=self.dhcp_server,
                                       boot_file=req.boot_file,
                                       yiaddr=self.ip_pool[req_eth.src][0],
                                       xid=req.xid,
                                       options=req.options))
        self.host_check()
        # self.logger.info("ASSEMBLED ACK: %s" % ack_pkt)
        return ack_pkt

    def assemble_offer(self, port, pkt):
        #self.semaphore.acquire()
        disc_eth = pkt.get_protocol(ethernet.ethernet)
        disc_ipv4 = pkt.get_protocol(ipv4.ipv4)
        disc_udp = pkt.get_protocol(udp.udp)
        disc = pkt.get_protocol(dhcp.dhcp)
        try:
            disc.options.option_list.remove(
                next(opt for opt in disc.options.option_list if opt.tag == 50))
        except:
            pass
        disc.options.option_list.remove(
            next(opt for opt in disc.options.option_list if opt.tag == 55))
        disc.options.option_list.remove(
            next(opt for opt in disc.options.option_list if opt.tag == 53))
        disc.options.option_list.remove(
            next(opt for opt in disc.options.option_list if opt.tag == 12))
        disc.options.option_list.insert(
            0, dhcp.option(tag=1, value=self.bin_netmask))
        disc.options.option_list.insert(
            0, dhcp.option(tag=3, value=self.bin_server))
        disc.options.option_list.insert(
            0, dhcp.option(tag=6, value=self.bin_dns))
        # disc.options.option_list.insert(
        #     0, dhcp.option(tag=12, value=self.hostname))
        disc.options.option_list.insert(
            0, dhcp.option(tag=51, value=struct.pack('!I', self.release_time)))
        disc.options.option_list.insert(
            0, dhcp.option(tag=53, value=struct.pack('!B', 2)))
        # disc.options.option_list.insert(
        #     0, dhcp.option(tag=54, value=self.hostname))
        disc.options.option_list.insert(
            0, dhcp.option(tag=58, value=struct.pack('!I', self.release_time // 2)))
        disc.options.option_list.insert(
            0, dhcp.option(tag=59, value=struct.pack('!I', self.release_time * 7 // 8)))
        if disc_eth.src not in self.ip_pool:
            nid = random.choice(self.usable_id)
            nip = self.ip_addr + str(nid)
            #print("new host in,mac:" + disc_eth.src + ",ip:" + nip)
            self.usable_id.remove(nid)
            self.ip_pool[disc_eth.src] = [nip, time.perf_counter()]
        else:
            self.ip_pool[disc_eth.src][1] = time.perf_counter()
        #print(disc_eth.src, str(self.mac_port[disc_eth.src][1])+":"+str(self.mac_port[disc_eth.src][1]))
        h = switches.Host(disc_eth.src, str(self.mac_port[disc_eth.src][0])+":"+str(self.mac_port[disc_eth.src][1]))
        h.ipv4.append(self.ip_pool[disc_eth.src][0])
        self.send_event_to_observers(event.EventHostAdd(h))
        nip = self.ip_pool[disc_eth.src][0]
        offer_pkt = packet.Packet()
        offer_pkt.add_protocol(ethernet.ethernet(
            ethertype=disc_eth.ethertype, dst=disc_eth.src, src=self.hw_addr))
        offer_pkt.add_protocol(
            ipv4.ipv4(dst=disc_ipv4.dst, src=self.dhcp_server, proto=disc_ipv4.proto))
        offer_pkt.add_protocol(udp.udp(src_port=67, dst_port=68))
        offer_pkt.add_protocol(dhcp.dhcp(op=2, chaddr=disc_eth.src,
                                         siaddr=self.dhcp_server,
                                         boot_file=disc.boot_file,
                                         yiaddr=nip,
                                         xid=disc.xid,
                                         options=disc.options))
        return offer_pkt

    def get_state(self, pkt_dhcp):
        """
        :param pkt_dhcp: 解析后的dhcp报文
        :return: dhcp报文的消息类型
        """
        dhcp_state = ord(
            [opt for opt in pkt_dhcp.options.option_list if opt.tag == 53][0].value)
        if dhcp_state == 1:
            state = 'DHCPDISCOVER'
        elif dhcp_state == 2:
            state = 'DHCPOFFER'
        elif dhcp_state == 3:
            state = 'DHCPREQUEST'
        elif dhcp_state == 4:
            state = 'DHCPDECLINE'
        elif dhcp_state == 5:
            state = 'DHCPACK'
        elif dhcp_state == 6:
            state = 'DHCPNAK'
        elif dhcp_state == 7:
            state = 'DHCPRELEASE'
        elif dhcp_state == 8:
            state = 'DHCPINFORM'
        return state

    def _handle_dhcp(self, datapath, port, pkt):
        """
        :param datapath:交换机标识
        :param port: 交换机端口
        :param pkt: DHCP报文
       根据DHCP的消息类型发送不同类型的包
        """
        pkt_dhcp = pkt.get_protocol(dhcp.dhcp)
        dhcp_state = self.get_state(pkt_dhcp)
        if dhcp_state == 'DHCPDISCOVER':
            self._send_packet(datapath, port, self.assemble_offer(port, pkt))
        elif dhcp_state == 'DHCPREQUEST':
            self._send_packet(datapath, port, self.assemble_ack(pkt))
        else:
            return

    def _send_packet(self, datapath, port, pkt):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        if pkt is None:
            return
        pkt.serialize()
        # print("packet-out %s" % (pkt,))
        data = pkt.data
        actions = [parser.OFPActionOutput(port=port)]
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=ofproto.OFPP_CONTROLLER,
                                  actions=actions,
                                  data=data)
        datapath.send_msg(out)



    # 定期检查超时未能更新的主机，删除之
    def host_check(self):
        # while self.is_active:
        #     self.check_event.clear()
        for m in list(self.ip_pool.keys()):
            if time.perf_counter() - self.ip_pool[m][1] > 30:
                #print(time.perf_counter(), self.ip_pool[m][2])
                id = int(self.ip_pool[m][0].split('.')[-1])
                #print(m, str(self.mac_port[m][0])+":"+str(self.mac_port[m][1]))
                h = switches.Host(m, str(self.mac_port[m][0])+":"+str(self.mac_port[m][1]))
                h.ipv4.append(self.ip_pool[m][0])
                self.send_event_to_observers(event.EventHostDelete(h))
                del self.ip_pool[m]
                del self.mac_port[m]
                self.usable_id.append(id)
            # self.check_event.wait(30)

    def arp_handle(self, ev):
        """
        获取到源主机发送的ARP请求包，伪装成目的主机，给源主机发送ARP响应
        :param ev:
        :return:
        """
        msg = ev.msg
        print("#############################################")
        datapath = msg.datapath
        dpid = datapath.id

        port = msg.match['in_port']
        pkt = packet.Packet(data=msg.data)
        pkt_eth = pkt.get_protocol(ethernet.ethernet)
        # if not pkt_eth:
        #     print("packet-in: %s" % (pkt_eth,))
        #     return
        # else:
        #     dst_mac = pkt_eth.dst
        #     eth_type = pkt_eth.ethertype

        # This 'if condition' is for learning the ip and mac addresses of hosts as well as .
        pkt_arp = pkt.get_protocol(arp.arp)
        if not pkt_arp:
            return
        else:
            print("datapath id: " + str(dpid))
            print("port: " + str(port))

            print("pkt_eth.dst: " + str(pkt_eth.dst))
            print("pkt_eth.src: " + str(pkt_eth.src))
            print("pkt_arp: " + str(pkt_arp))
            print("pkt_arp:src_ip: " + str(pkt_arp.src_ip))
            print("pkt_arp:dst_ip: " + str(pkt_arp.dst_ip))
            print("pkt_arp:src_mac: " + str(pkt_arp.src_mac))
            print("pkt_arp:dst_mac: " + str(pkt_arp.dst_mac))

            # Destination and source ip address
            dst_ip = pkt_arp.dst_ip
            src_ip = pkt_arp.src_ip

            # Destination and source mac address (HW address)
            dst_mac = pkt_arp.dst_mac
            src_mac = pkt_arp.src_mac
            target_mac = self.get_mac_by_ip(dst_ip)     # 源主机希望获得的目的主机的mac
            self._handle_arp(datapath, port, pkt_eth, pkt_arp, target_mac, dst_ip)

    def get_mac_by_ip(self, target_ip):
        for item in self.ip_pool:
            ip = self.ip_pool[item][0]
            if ip == target_ip:
                return item

    def _handle_arp(self, datapath, port, pkt_ethernet, pkt_arp, target_hw_addr, target_ip_addr):
        """
        构造一个ARP响应包并发送给源主机
        :return:
        """
        if pkt_arp.opcode != arp.ARP_REQUEST:
            return
        pkt = packet.Packet()
        pkt.add_protocol(ethernet.ethernet(ethertype=pkt_ethernet.ethertype,
                                           dst=pkt_ethernet.src,
                                           src=target_hw_addr))
        pkt.add_protocol(arp.arp(opcode=arp.ARP_REPLY,
                                 src_mac=target_hw_addr,
                                 src_ip=target_ip_addr,
                                 dst_mac=pkt_arp.src_mac,
                                 dst_ip=pkt_arp.src_ip))
        self._send_packet(datapath, port, pkt)

    def _send_packet(self, datapath, port, pkt):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        pkt.serialize()
        data = pkt.data
        actions = [parser.OFPActionOutput(port=port)]
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=ofproto.OFPP_CONTROLLER,
                                  actions=actions,
                                  data=data)
        datapath.send_msg(out)