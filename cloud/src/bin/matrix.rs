use color_eyre::eyre;
use eyre::Error;
use itertools::Itertools;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;
use std::sync::{Arc};
use tokio::sync::Mutex;
use structopt::StructOpt;
use tracing::{debug, info, trace};
use tsunami::providers::{aws, baremetal, azure};
use tsunami::{Machine};

#[derive(StructOpt)]
struct Opt {
    #[structopt(long = "cfg", short = "f")]
    cfg: String,

    #[structopt(long = "pause")]
    pause: bool,
}

#[derive(Deserialize, Serialize, Clone)]
enum Node {
    Aws {
        region: String,
    },
    Azure {
        region: String,
    },
    Baremetal {
        name: String,
        ip: String,
        user: String,
        iface: String,
    },
}

impl Node {
    fn get_name(&self) -> String {
        match self {
            Node::Aws { region: r } => format!("aws_{}", r.replace("-", "")),
            Node::Azure { region: r } => format!("az_{}", r.replace("-", "")),
            Node::Baremetal { name: n, .. } => n.clone(),
        }
    }
}

#[derive(Deserialize, Serialize, Clone)]
struct Exp {
    from: Node,
    to: Node,
}

fn register_node(
    b: &mut TsunamiBuilder,
    baremetal_meta: &mut HashMap<String, (String, String, String)>,
    r: Node,
) -> Result<String, Error> {
    match r {
        Node::Aws { region: r } => {
            let m = MachineSetup::default()
                .region(r.clone().parse()?)
                .instance_type("t3.medium")
                .setup(|ssh| {
                    cloud::install_basic_packages(ssh)
                        .await?;
                    debug!("finished apt install");
                    cloud::get_tools(ssh).await?;
                    Ok(())
                });

            let name = format!("aws_{}", r.replace("-", ""));
            b.add(name.clone(), Setup::AWS(m));
            Ok(name)
        }
        Node::Azure { region: r } => {
            let m = azure::Setup::default().region(r.clone().parse()?).setup(|vm| Box::pin(async move {
                cloud::install_basic_packages(ssh)
                    .await?;
                debug!("finished apt install");
                cloud::get_tools(ssh).await?;
                Ok(())
            }));
        }
        Node::Baremetal {
            name: n,
            ip: i,
            user: u,
            iface: f,
        } => {
            let m = tsunami::providers::baremetal::Setup::new((i.as_str(), 22), Some(u.clone()))?
                .setup(|ssh, log| {
                    cloud::install_basic_packages(ssh)
                    ssh.cmd("sudo sysctl -w net.ipv4.tcp_rmem=\"4096000 50331648 50331648\"")
                        .map(|(_, _)| ())?;
                    ssh.cmd("sudo sysctl -w net.ipv4.tcp_limit_output_bytes=\"250000000\"")
                        .map(|(_, _)| ())?;
                    if let Err(_) = ssh
                        .cmd("git clone --recursive https://github.com/bundler-project/tools")
                        .map(|(_, _)| ())
                    {
                        ssh.cmd("cd tools && git pull origin master && git submodule update --init --recursive").map(|(_, _)| ())?;
                    }

                    ssh.cmd("make -C tools udping/target/debug/udping_server udping/target/debug/udping_client")
                        .map(|(_, _)| ())?;

                    // TODO check that opt.recv_iface exists
                    Ok(())
                });
            baremetal_meta.insert(n.clone(), (i, u, f));
            b.add(n.clone(), Setup::Bare(m));
            Ok(n)
        }
    }
}

fn check_path(from: &str, to: &str) -> bool {
    let control_path_string = format!("./{}-{}/control", from, to);
    let iperf_path_string = format!("./{}-{}/iperf", from, to);
    let bundler_path_string = format!("./{}-{}/bundler", from, to);
    let control_path = Path::new(control_path_string.as_str());
    let iperf_path = Path::new(iperf_path_string.as_str());
    let bundler_path = Path::new(bundler_path_string.as_str());

    if let Err(_) = std::fs::create_dir_all(control_path) {
        return true;
    }

    if let Err(_) = std::fs::create_dir_all(iperf_path) {
        return true;
    }

    if let Err(_) = std::fs::create_dir_all(bundler_path) {
        return true;
    }

    if Path::new(&control_path_string).join("bmon.log").exists()
        && Path::new(&control_path_string).join("udping.log").exists()
        && Path::new(&iperf_path_string).join("bmon.log").exists()
        && Path::new(&iperf_path_string).join("udping.log").exists()
        && Path::new(&bundler_path_string).join("bmon.log").exists()
        && Path::new(&bundler_path_string).join("udping.log").exists()
    {
        return false;
    } else {
        return true;
    }
}

fn main() -> Result<(), Error> {
    let opt = Opt::from_args();

    let f = std::fs::File::open(opt.cfg)?;
    let r = std::io::BufReader::new(f);
    let u: Vec<Exp> = serde_json::from_reader(r)?;

    let mut pairs = vec![];

    let mut baremetal_meta = HashMap::new();
    for r in u {
        if check_path(&r.from.get_name(), &r.to.get_name()) {
            let from_name = register_node(&mut b, &mut baremetal_meta, r.from)?;
            let to_name = register_node(&mut b, &mut baremetal_meta, r.to)?;
            pairs.push((from_name, to_name));
        } else {
            info!(sender = ?&r.from.get_name(), recevier = ?&r.to.get_name(), "skipping experiment");
        }
    }

    let mut aws_launcher = aws::Launcher::default();
    let mut az_launcher = azure::Launcher::default();
    let mut baremetal_launcher  = baremetal::Machine::default();

            let vms: HashMap<String, Arc<Mutex<Machine>>> = vms
                .into_iter()
                .map(|(k, v)| (k, Arc::new(Mutex::new(v))))
                .collect();

            pairs
                .into_par_iter()
                .map(|(from, to)| {
                    let sender_lock = vms.get(&from).expect("vms get from").clone();
                    let receiver_lock = vms.get(&to).expect("vms get to").clone();
                    let (sender, receiver) = if from < to {
                        info!("waiting for lock");
                        let sender = sender_lock.lock().unwrap();
                        let receiver = receiver_lock.lock().unwrap();
                        (sender, receiver)
                    } else if from > to {
                        info!("waiting for lock");
                        let receiver = receiver_lock.lock().unwrap();
                        let sender = sender_lock.lock().unwrap();
                        (sender, receiver)
                    } else {
                        return Ok(());
                    };

                    let (sender_user, sender_iface) = baremetal_meta
                        .get(&from)
                        .map(|(_, user, iface)| (user.clone(), iface.clone()))
                        .unwrap_or_else(|| ("ubuntu".to_string(), "ens5".to_string()));

                    let (receiver_user, receiver_iface) = baremetal_meta
                        .get(&to)
                        .map(|(_, user, iface)| (user.clone(), iface.clone()))
                        .unwrap_or_else(|| ("ubuntu".to_string(), "ens5".to_string()));

                    info!("locked pair");

                    let sender_ssh = sender.ssh.as_ref().expect("sender ssh connection");
                    let receiver_ssh = receiver.ssh.as_ref().expect("receiver ssh connection");

                    let sender_node = cloud::Node {
                        ssh: sender_ssh,
                        name: &from,
                        ip: &sender.public_ip,
                        iface: &sender_iface,
                        user: &sender_user,
                    };

                    let receiver_node = cloud::Node {
                        ssh: receiver_ssh,
                        name: &to,
                        ip: &receiver.public_ip,
                        iface: &receiver_iface,
                        user: &receiver_user,
                    };

                    trace!("starting pair";
                        "sender_user" => sender_node.user,
                        "receiver_user" => receiver_node.user,
                    );

                    cloud::reset(&sender_node, &receiver_node);

                    let control_path_string = format!("./{}-{}/control", from, to);
                    let control_path = Path::new(control_path_string.as_str());
                    std::fs::create_dir_all(control_path)?;

                    if Path::new(&control_path_string).join("bmon.log").exists()
                        && Path::new(&control_path_string).join("udping.log").exists()
                    {
                        info!( "skipping control experiment");
                    } else {
                        info!( "running control experiment");
                        cloud::nobundler_exp_control(
                            &control_path,
                            &sender_node,
                            &receiver_node,
                        )
                        .context(format!("control experiment {} -> {}", &from, &to))?;
                    }

                    cloud::reset(&sender_node, &receiver_node);

                    let iperf_path_string = format!("./{}-{}/iperf", from, to);
                    let iperf_path = Path::new(iperf_path_string.as_str());
                    std::fs::create_dir_all(iperf_path)?;
                    //if Path::new(&iperf_path_string).join("bmon.log").exists()
                    //    && Path::new(&iperf_path_string).join("udping.log").exists()
                    //{
                    //    info!("skipping iperf experiment");
                    //} else {
                    //}

                    let bundler_path_string = format!("./{}-{}/bundler", from, to);
                    let bundler_path = Path::new(bundler_path_string.as_str());
                    std::fs::create_dir_all(bundler_path)?;
                    if Path::new(&bundler_path_string).join("bmon.log").exists()
                        && Path::new(&bundler_path_string).join("udping.log").exists()
                    {
                        info!("skipping bundler experiment");
                    } else {
                        info!("running iperf experiment");
                        cloud::nobundler_exp_iperf(&iperf_path, &sender_node, &receiver_node)
                            .context(format!("iperf experiment {} -> {}", &from, &to))?;

                        cloud::reset(&sender_node, &receiver_node);

                        //info!("running bundler experiment");
                        //cloud::bundler_exp_iperf(
                        //    &bundler_path,
                        //    &log,
                        //    &sender_node,
                        //    &receiver_node,
                        //    "sfq",
                        //    "1000mbit",
                        //)
                        //.context(format!("bundler experiment {} -> {}", &from, &to))?;
                    }

                    cloud::reset(&sender_node, &receiver_node);

                    info!(log, "pair done");
                    Ok(())
                })
                .collect()

    info!("collecting logs");

    std::process::Command::new("python3")
        .arg("parse_udping.py")
        .arg(".")
        .spawn()?
        .wait()?;

    std::process::Command::new("Rscript")
        .arg("plot_paths.r")
        .spawn()?
        .wait()?;

    std::process::Command::new("python3")
        .arg("plot_ccp.py")
        .spawn()?
        .wait()?;

    Ok(())
}

fn matrix(vms: &HashMap<String, Machine>) -> impl Iterator<Item = (String, String)> {
    let names: Vec<String> = vms.keys().cloned().collect();
    let names2 = names.clone();

    names.into_iter().cartesian_product(names2)
}
