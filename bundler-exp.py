#!/usr/bin/python3

import argparse
import subprocess as sh
import time
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--outdir', type=str, dest='outdir')
parser.add_argument('--three_machines', action='store_true', dest='three_machines')

parser.add_argument('--no_bundler', action='store_false', dest='usebundler')
parser.add_argument('--qdisc', type=str, dest='qdisc')
parser.add_argument('--alg', type=str, dest='alg')
parser.add_argument('--static_epoch', action='store_false', dest='dynamic_epoch')
parser.add_argument('--samplerate', type=int, dest='samplerate')

parser.add_argument('--time', type=int, dest='time')
parser.add_argument('--cross_traffic', type=str, dest='cross_traffic', default=None)
parser.add_argument('--conns', type=int, dest='conns')
parser.add_argument('--fct_experiment', action='store_true', dest='do_fct_experiment')
parser.add_argument('--load', type=str, dest='load')
parser.add_argument('--seed', type=int, dest='seed')
parser.add_argument('--reqs', type=int, dest='reqs')
parser.add_argument('--backlogged_bundle', action='store_true', dest='backlogged_bundle')

nimbus = 'sudo ~/nimbus/target/release/nimbus --ipc=unix --use_switching=false --flow_mode=Delay --bw_est_mode=false --pulse_size=0.01 2> {}/nimbus.out'
bbr = 'sudo ~/bbr/target/release/bbr --ipc=unix 2> {}/bbr.out'
osc = 'sudo python ~/portus/python/osc.py'
copa = 'sudo ~/ccp_copa/target/debug/copa --ipc=unix --delta_mode=NoTCP --default_delta=0.125 2> {}/copa.out'
algs = {
    'nimbus': nimbus,
    'bbr': bbr,
    'osc': osc,
    'copa': copa,
}

def kill_everything():
    sh.run('ssh 10.1.1.2 sudo pkill -9 inbox', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 nimbus', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 bbr', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 iperf', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 -f ./bin/server', shell=True)
    sh.run('ssh 192.168.1.5 sudo pkill -9 -f ./bin/server', shell=True)
    sh.run('ssh 192.168.1.5 sudo pkill -9 iperf', shell=True)
    sh.run('sudo pkill -9 outbox', shell=True)
    sh.run('sudo pkill -9 iperf', shell=True)

def write_etg_config(name, args):
    with open(name, 'w') as f:
        for p in range(5000, 5000 + args.conns):
            f.write("server 192.168.1.5 {}\n".format(p))
        f.write("req_size_dist ./CAIDA_CDF\n")
        f.write("fanout 1 100\n")
        if args.backlogged_bundle:
            f.write("persistent_servers 1\n")
        f.write("load {}\n".format(args.load))
        f.write("num_reqs {}\n".format(args.reqs))

def remote_script(args):
    inbox = 'sudo ~/bundler/box/target/release/inbox --iface=10gp1 --handle_major={} --handle_minor=0x0 --port=28316 --use_dynamic_sample_rate={} --sample_rate={} 2> {}/inbox.out'.format(args.qdisc, args.dynamic_samplerate, args.samplerate, args.outdir)
    if not args.do_fct_experiment:
        exc = '~/iperf/src/iperf -s -p 5000 --reverse -i 1 -t {} -P {} > {}/iperf-server.out'.format(args.time, args.conns, args.outdir)
    else:
        exc = 'cd ~/bundler/scripts && ./run-multiple-server.sh 5000 {}'.format(args.conns)

    print(inbox)
    print(exc)

    with open('remote.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        f.write('rm -rf ~/{}\n'.format(args.outdir))
        f.write('mkdir -p ~/{}\n'.format(args.outdir))
        if args.use_bundler:
            f.write('echo "starting inbox: $(date)"\n')
            f.write(inbox + ' &\n')
            f.write('sleep 1\n')
            f.write('echo "starting alg: $(date)"\n')
            f.write(args.alg.format(args.outdir) + ' &\n')
        if not args.three_machines:
            f.write(exc + '\n')

    sh.run('chmod +x remote.sh', shell=True)
    sh.run('scp ./remote.sh 10.1.1.2:', shell=True)

    if args.three_machines:
        with open('remote.sh', 'w') as f:
            f.write('#!/bin/bash\n\n')
            f.write('rm -rf ~/{}\n'.format(args.outdir))
            f.write('mkdir -p ~/{}\n'.format(args.outdir))
            f.write('sudo dd if=/dev/null of=/proc/net/tcpprobe bs=256 &\n')
            f.write('sudo dd if=/proc/net/tcpprobe of={}/tcpprobe.out bs=256 &\n'.format(args.outdir))
            f.write(exc + '\n')
            f.write('sudo killall dd\n')
        sh.run('chmod +x remote.sh', shell=True)
        sh.run('scp ./remote.sh 192.168.1.5:', shell=True)

    sh.Popen('ssh 10.1.1.2 ~/remote.sh' , shell=True)
    sh.Popen('ssh 192.168.1.5 ~/remote.sh' , shell=True)

def local_script(args):
    outbox = 'sudo ~/bundler/box/target/release/outbox --filter "src portrange 5000-6000" --iface ingress --inbox 10.1.1.2:28316 {} --sample_rate {} 2> {}/outbox.out'.format(
        "--no_ethernet",
        args.samplerate,
        args.outdir,
    )
    if not args.do_fct_experiment:
        exc = '~/iperf/src/iperf -c {} -p 5000 --reverse -i 1 -P {} > {}/iperf-client.out'.format(
            '192.168.1.5' if args.three_machines else '10.1.1.2',
            args.conns,
            args.outdir,
        )
    else:
        exc = '~/bundler/scripts/empiricial-traffic-gen/bin/client -c ~/bundler/scripts/bundlerConfig -l {}/ -s {}'.format(
            args.outdir,
            args.seed,
        )

    print(outbox)
    print(exc)

    with open('local.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        if args.use_bundler:
            f.write('sleep 1\n')
            f.write(outbox + ' &\n')
        f.write('sleep 1\n')
        f.write('echo "starting iperf client: $(date)"\n')
        f.write(exc + '\n')
        if args.cross_traffic == 'reqs':
            f.write("~/bundler/scripts/empiricial-traffic-gen/bin/client -c ~/bundler/scripts/empiricial-traffic-gen/crossTrafficConfig -l {} -s 42\n".format(
                args.outdir + "/cross/"
            ))

    sh.run('chmod +x local.sh', shell=True)
    sh.run('rm -rf ./{}\n'.format(args.outdir), shell=True)
    sh.run('mkdir -p ./{}\n'.format(args.outdir), shell=True)
    if args.cross_traffic is not None:
        sh.run("mkdir -p {}/{}\n".format(args.outdir, "cross"), shell=True)
    mahimahi = 'mm-delay 25 mm-link --cbr 96M 96M --downlink-queue="droptail" --downlink-queue-args="packets=1200" --uplink-queue="droptail" --uplink-queue-args="packets=1200" --downlink-log={}/mahimahi.log ./local.sh'.format(args.outdir)
    sh.run(mahimahi, shell=True)


def run_single_experiment(args):
    if args.do_fct_experiment:
        args.time = None
    else:
        args.load = None
        args.reqs = None
        args.seed = None
        if args.time is None:
            print('please give a time')
            sys.exit(1)
        if args.conns > 32:
            print("are you sure? running 32 parallel iperf connections")
            sys.exit(1)
        if args.samplerate is None:
            args.samplerate = 128
    args.dynamic_samplerate = 'true' if args.dynamic_epoch else 'false'
    args.use_bundler = args.usebundler
    args.alg = algs[args.alg]

    kill_everything()
    a = vars(args)
    commit = sh.check_output('git rev-parse HEAD', shell=True)
    commit = commit.decode('utf-8')[:-1]
    print('commit {}'.format(str(commit)))
    for k in sorted(a):
        print(k, a[k])

    if args.do_fct_experiment:
        write_etg_config('bundlerConfig', args)
    if args.cross_traffic == 'reqs':
        write_etg_config('crossTrafficConfig', "12Mbps", 10, 1000)
    remote_script(args)
    local_script(args)

    sh.run('ssh 10.1.1.2 "grep "sch_bundle_inbox" /var/log/syslog > ~/{}/qdisc.log"'.format(args.outdir), shell=True)
    sh.run('scp 10.1.1.2:~/{0}/* ./{0}'.format(args.outdir), shell=True)
    if args.three_machines:
        sh.run('scp 192.168.1.5:~/{0}/* ./{0}'.format(args.outdir), shell=True)
    if args.do_fct_experiment:
        sh.run("mv ./bundlerConfig ./{}".format(args.outdir), shell=True)

    kill_everything()

    sh.run('mm-graph {}/mahimahi.log 50'.format(args.outdir), shell=True)

if __name__ == '__main__':
    args = parser.parse_args()
    run_single_experiment(args)
