import sys
import agenda
from collections import namedtuple
import os
import time
import io

from util import *
from ccp import get_ccp_binary_path

class Traffic:
    def __init__(self, *args, **kwargs):
        self.traffic = None

    def __getattr__(self, attr):
        return getattr(self.traffic, attr)

class IperfTraffic(Traffic):
    trafficType = namedtuple('IperfTraffic', ['port', 'report_interval', 'length', 'num_flows', 'alg', 'start_delay'])

    def __init__(self, *args, **kwargs):
        self.traffic = IperfTraffic.trafficType(**kwargs)

    def __str__(self):
        return "iperf.{}.{}".format(self.traffic.alg, self.traffic.num_flows)

    def start_client(self, config, node, in_bundler, execute):
        agenda.subtask("Start iperf client ({})".format(self))
        iperf_out = os.path.join(config['iteration_dir'], "iperf_client_{}.log".format(self.port))
        check_bundler_port(in_bundler, self, config)
        cmd = "sleep {delay} && {path} -c {ip} -p {port} --reverse -i {report_interval} -t {length} -P {num_flows} -Z {alg}".format(
            path=os.path.join(config['structure']['bundler_root'], 'iperf/src/iperf'),
            ip=config['topology']['sender']['ifaces'][0]['addr'] if in_bundler else '$MAHIMAHI_BASE',
            port=self.port,
            report_interval=self.report_interval,
            length=self.length,
            num_flows=self.num_flows,
            alg=self.alg,
            delay=self.start_delay
        )

        config['iteration_outputs'].append((node, iperf_out))

        if execute:
            expect(
                node.run(cmd,
                    background=True,
                    stdout=iperf_out,
                    stderr=iperf_out
                ),
                "Failed to start iperf client on {}".format(node.addr)
            )
        else:
            return cmd + " > {}".format(iperf_out)

    def start_server(self, config, node, execute):
        if int(self.port) == 8900 or int(self.port) == 8901:
            agenda.subtask("Skipping server!")
            return
        agenda.subtask("Start iperf server ({})".format(self))
        iperf_out = os.path.join(config['iteration_dir'], "iperf_server_{}.log".format(self.port))
        expect(
            node.run(
                "{path} -s -p {port} --reverse -i {report_interval} -t {length} -P {num_flows} -Z {alg}".format(
                    path=os.path.join(config['structure']['bundler_root'], 'iperf/src/iperf'),
                    port=self.port,
                    report_interval=self.report_interval,
                    length=self.length,
                    num_flows=self.num_flows,
                    alg=self.alg,
                ),
                background=True,
                stdout=iperf_out,
                stderr=iperf_out
            ),
            "Failed to start iperf server on {}".format(node.addr)
        )

        if not config['args'].dry_run:
            time.sleep(1)

        node.check_file('Server listening on TCP port', iperf_out)
        config['iteration_outputs'].append((node, iperf_out))
        return iperf_out

class CBRTraffic(Traffic):
    trafficType = namedtuple('CBRTraffic', ['port', 'report_interval', 'length', 'rate', 'cwnd_cap', 'start_delay'])

    def __init__(self, *args, **kwargs):
        self.traffic = CBRTraffic.trafficType(**kwargs)

    def __str__(self):
        return "cbr.{}".format(self.rate)

    def start_client(self, config, node, in_bundler, execute):
        agenda.subtask("Start cbr client ({})".format(self))
        iperf_out = os.path.join(config['iteration_dir'], "cbr_client_{}.log".format(self.port))
        check_bundler_port(in_bundler, self, config)

        cmd = "sleep {delay} && {path} -c {ip} -p {port} --reverse -i {report_interval} -t {length}".format(
            path=os.path.join(config['structure']['bundler_root'], 'iperf/src/iperf'),
            ip=config['topology']['sender']['ifaces'][0]['addr'] if in_bundler else '$MAHIMAHI_BASE',
            port=self.port,
            report_interval=self.report_interval,
            length=self.length,
            delay=self.start_delay
        )

        config['iteration_outputs'].append((node, iperf_out))

        if execute:
            expect(
                node.run(cmd,
                    background=True,
                    stdout=iperf_out,
                    stderr=iperf_out
                ),
                "Failed to start iperf client on {}".format(node.addr)
            )
        else:
            return cmd + " > {}".format(iperf_out)

    def start_server(self, config, node, execute):
        agenda.subtask("Start cbr server ({})".format(self))
        iperf_out = os.path.join(config['iteration_dir'], "cbr_server_{}.log".format(self.port))

        ccp_binary = get_ccp_binary_path(config, 'const')
        #ccp_binary_name = ccp_binary.split('/')[-1]
        ccp_out = os.path.join(config['iteration_dir'], "ccp_const.log")

        agenda.subtask("Starting CBR CCP agent")
        expect(node.run(
            "{ccp_path} --ipc=netlink --rate={rate} --cwnd_cap={cwnd_cap}".format(
                ccp_path=ccp_binary,
                rate=self.rate,
                cwnd_cap=self.cwnd_cap,
            ),
            sudo=True,
            background=True,
            stdout=ccp_out,
            stderr=ccp_out,
        ), "Failed to start ccp_const agent")
         
        expect(
            node.run(
                "{path} -s -p {port} --reverse -i {report_interval} -t {length} -Z ccp".format(
                    path=os.path.join(config['structure']['bundler_root'], 'iperf/src/iperf'),
                    port=self.port,
                    report_interval=self.report_interval,
                    length=self.length,
                ),
                background=True,
                stdout=iperf_out,
                stderr=iperf_out
            ),
            "Failed to start iperf server on {}".format(node.addr)
        )

        if not config['args'].dry_run:
            time.sleep(2)

        node.check_file('Server listening on TCP port', iperf_out)
        node.check_proc("ccp_const", ccp_out)
        node.check_file('starting CCP', ccp_out)
        config['iteration_outputs'].append((node, iperf_out))
        config['iteration_outputs'].append((node, ccp_out))
        return iperf_out

class PoissonTraffic(Traffic):
    trafficType = namedtuple('PoissonTraffic', ['start_port', 'num_conns', 'num_backlogged', 'num_reqs', 'distribution', 'fanout', 'load', 'congalg', "seed", 'start_delay'])
    def __init__(self, *args, **kwargs):
        self.traffic = PoissonTraffic.trafficType(**kwargs)

    def __str__(self):
        return "poisson.{}.{}.{}".format(self.traffic.distribution.split("_")[0], self.traffic.load, self.traffic.congalg)


    def create_etg_config(self, node, global_config, f):
        port_start = self.start_port
        num_conns = int(self.num_conns)
        num_backlogged = int(self.num_backlogged)
        for p in range(port_start, port_start + num_conns):
            f.write("server {} {}\n".format(global_config['topology']['sender']['ifaces'][0]['addr'], p))
        dist_full_path = node.local_path(os.path.join(global_config['distribution_dir'], self.distribution))
        f.write(f"req_size_dist {dist_full_path}\n")
        f.write("fanout {}\n".format(self.fanout))
        if num_backlogged:
            f.write("persistent_servers {}\n".format(num_backlogged))
        f.write("load {}Mbps\n".format(self.load))
        f.write("num_reqs {}\n".format(self.num_reqs))

    def start_client(self, config, node, in_bundler, execute):
        agenda.subtask("Create ETG config file")

        if self.start_port < config['parameters']['bg_port_start'] or self.start_port + self.num_conns > config['parameters']['bg_port_end']:
            fatal_warn("Requested poisson traffic would be outside of outbox portrange ({}-{})".format(
                config['parameters']['bg_port_start'], config['parameters']['bg_port_end']
            ))

        i=1
        etg_config_path = os.path.join(config['iteration_dir'], f"etgConfig{i}")
        while node.file_exists(etg_config_path) and not config['args'].dry_run:
            i+=1
            etg_config_path = os.path.join(config['iteration_dir'], f"etgConfig{i}")
        with io.StringIO() as etg_config:
            self.create_etg_config(node, config, etg_config)
            node.put(etg_config, remote=os.path.join(config['iteration_dir'], f"etgConfig{i}"))

        etg_out = os.path.join(config['iteration_dir'], "{}".format(i))

        # NOTE: using cd + relative paths instead of absolute because etg has a buffer size of 80 for filenames
        cmd = "sleep {delay} && cd {wd} && {path} -c {config} -l {out_prefix} -s {seed}".format(
            wd=config['iteration_dir'],
            path=config['etg_client_path'],
            config=os.path.basename(etg_config_path),
            out_prefix=str(i),
            seed=self.seed,
            delay=self.start_delay
        )

        config['iteration_outputs'].append((node, etg_out + "_flows.out"))
        config['iteration_outputs'].append((node, etg_out + "_reqs.out"))

        if execute:
            expect(
                node.run(cmd,
                    background=True,
                    stdout=etg_out,
                    stderr=etg_out,
                ),
                "Failed to start poisson client on {}".format(node.addr)
            )
        else:
            return cmd

    def start_server(self, config, node, execute):
        agenda.subtask(f"Start ETG server ({self}) on {node.addr}")

        i=1
        etg_out = os.path.join(config['iteration_dir'], "etg_server{}.log".format(i))
        while node.file_exists(etg_out) and not config['args'].dry_run:
            i+=1
            etg_out = os.path.join(config['iteration_dir'], "etg_server{}.log".format(i))

        expect(
            node.run(
                "{sh} {start} {conns} {alg}".format(
                    sh=config['etg_server_path'],
                    start=self.start_port,
                    conns=self.num_conns,
                    alg=self.congalg
                ),
                wd=os.path.join(config['structure']['bundler_root'], 'empirical-traffic-gen'),
                stdout=etg_out,
                stderr=etg_out,
                background=True,
            ),
            "Failed to start poisson servers on {}".format(node.addr)
        )

        if not config['args'].dry_run:
            time.sleep(1)
            num_servers_running = int(node.run("pgrep -c etgServer").stdout.strip())
        else:
            num_servers_running = self.num_conns
        if num_servers_running != self.num_conns:
            fatal_warn("self pattern requested {} servers, but only {} are running properly.".format(self.num_conns, num_servers_running), exit=False)
            with io.BytesIO() as f:
                node.get(node.local_path(etg_out), local=f)
                print(f.getvalue().decode("utf-8"))
            sys.exit(1)

        config['iteration_outputs'].append((node, etg_out))
        return etg_out

def create_traffic_config(traffic, exp):
    for t in traffic:
        if t['source'] == 'iperf':
            yield IperfTraffic(
                port=t['port'],
                report_interval=1,
                length=t['length'],
                num_flows=t['flows'],
                alg=t['alg'],
                start_delay=t['start_delay']
            )
        elif t['source'] == 'cbr':
            yield CBRTraffic(
                port=t['port'],
                report_interval=1,
                length=t['length'],
                rate=t['rate'],
                cwnd_cap=t['cwnd_cap'],
                start_delay=t['start_delay']
            )
        elif t['source'] == 'poisson':
            yield PoissonTraffic(
                start_port=t['start_port'],
                num_conns=t['conns'],
                num_backlogged=t['backlogged'],
                num_reqs=t['reqs'],
                distribution=t['dist'],
                congalg=t['alg'],
                seed=exp.seed,
                load=(int(eval(t['load']) * exp.rate)),
                start_delay=t['start_delay'],
                fanout='1 100'
        )

def check_bundler_port(in_bundler, traffic, config):
    if in_bundler and (traffic.port < config['parameters']['bg_port_start'] or traffic.port > config['parameters']['bg_port_end']):
        fatal_warn("Bundle traffic ({}) is outside of bundle capture region! ({}-{})".format(
            traffic.port, config['parameters']['bg_port_start'], config['parameters']['bg_port_end']
        ))
    elif not in_bundler and traffic.port > config['parameters']['bg_port_start'] and traffic.port < config['parameters']['bg_port_end']:
        fatal_warn("Cross traffic ({}) is in bundle capture region! ({}-{})".format(
            traffic.port, config['parameters']['bg_port_start'], config['parameters']['bg_port_end']
        ))

def start_multiple_client(config, node, traffic, in_bundler, execute=True):
    for t in traffic:
        yield start_client(config, node, t, in_bundler, execute)

def start_client(config, node, traffic, in_bundler, execute=True):
    if not traffic:
        return None if execute else ''
    return traffic.start_client(config, node, in_bundler, execute)

def start_multiple_server(config, node, traffic, execute=True):
    for t in traffic:
        yield start_server(config, node, t, execute)

def start_server(config, node, traffic, execute=True):
    if not traffic:
        return None if execute else ''
    return traffic.start_server(config, node, execute)
