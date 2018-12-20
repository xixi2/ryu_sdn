INF = 10000


def floyd(n, dis):
    """
    path:计算的路径
    :param switchs: 交换机列表
    :param dis: dis[i][j]表示第i个节点到第j个节点的距离
    :return:
        dis: dis[i][j]表示交换机i到j的最短路径
        path: path[i][j]表示从结点i到结点j的最短路径上经过的最后一个中间结点
        如path[0][2]的最短路径经过的完整结点序列为：[0,1,2]，则
            首先在path中找到path[0][2]=1,说明从结点0到结点2上的而最后一个中间结点为1
            接下来继续从path中找到path[0][1]=0说明从结点0到结点1的最短路径上的最后一个中间结点已经是结点1本身，即从结点
            0到结点1的最短路径上没有其他中间结点，因此查找过程结束。
    """
    path = [([0] * n) for i in range(n)]
    # print('path: {0}'.format(path))
    for i in range(n):
        for j in range(n):
            path[i][j] = i
    for k in range(n):
        for i in range(n):
            for j in range(n):
                if dis[i][k] == INF or dis[k][j] == INF:
                    continue
                if dis[i][j] > dis[i][k] + dis[k][j]:
                    dis[i][j] = dis[i][k] + dis[k][j]
                    path[i][j] = path[k][j]
    return path, dis


def get_switch_sequence(src, dst, whole_path):
    """
    :param src: 源结点
    :param dst: 目的结点
    :param whole_path: 全局路径矩阵
    :return:
        reverse_one_path: 从源结点src到目的结点dst之间的最短路径上经过的完整交换机结点列
        依次从path中找到从源结点到目的结点的最短路径上的最后一个中间结点，形成一个完整的交换机结点序列
    """
    one_path = []
    one_path.append(dst)
    while True:
        in_node = whole_path[src][dst]
        # print('in_node: {0}, src: {1}, dst:{2}'.format(in_node, src, dst))
        if in_node != dst:
            one_path.append(in_node)
        dst = in_node
        if in_node == src:
            break
    reverse_one_path = one_path[::-1]
    return reverse_one_path


def get_all_short_path_sequence(n_switches, dis):
    """
    :param n_switches: 交换机个数
    :return:
        path_sequence：交换机i到j的最短路径上的交换机序号组成的序列
    """
    path_sequence = []
    # n_switches = len(switches)
    path, dis = floyd(n_switches, dis)
    for i in range(n_switches):
        # for j in range(i + 1, len(switches)):
        for j in range(n_switches):
            one_path = get_switch_sequence(i, j, path)  # 从结点i出发到结点j所经过的交换机序列
            path_sequence.append(one_path)
    return path_sequence


if __name__ == '__main__':
    switches = [1, 2, 3, 4]
    # switches = [0, 1, 2, 3, 4, 5]
    # dis = [[0, 8, INF, INF], [8, 0, 1, 4], [INF, 1, 0, 2], [INF, 4, 2, 0]]
    dis = [[0, 1000, 1, ], [1000, 0, 1], [1, 1, 0.]]
    # dis = [[0, 1, 1],[1, 0, INF],[1, INF, 0]]
    # dis = [[0, 1, 0],[1, 0, 1],[0, 1, 0]]

    # dis = [[0, 3, INF, INF, 2, 1], [3, 0, 4, 2, INF, 6], [INF, 4, 0, 1, INF, 7],
    #        [INF, 2, 1, 0, 5, INF], [2, INF, INF, 5, 0, 3], [1, 6, 7, INF, 3, 0]]

    # path, dis = floyd(switches, dis)
    # print('================path====================')
    # for item in path:
    #     print(item)
    # print('================dis====================')
    # for item in dis:
    #     print(item)
    # one_path = get_switch_sequence(0, 2, path)
    # print('one_path: {0}'.format(one_path))
    #
    # one_path = get_switch_sequence(0, 3, path)
    # print('one_path: {0}'.format(one_path))
    n_switches = 3
    path_sequence = get_all_short_path_sequence(n_switches, dis)
    for item in path_sequence:
        print('src: {0}, dst: {1}: seq: {2}'.format(item[0], item[-1], item))
