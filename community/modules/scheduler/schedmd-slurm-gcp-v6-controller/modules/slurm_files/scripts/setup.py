#!/usr/bin/env python3

# Copyright (C) SchedMD LLC.
# Copyright 2024 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import logging
import os
import shutil
import subprocess
import stat
import time
import yaml
from pathlib import Path
import grp, pwd

import util
from util import (
    lookup,
    dirs,
    slurmdirs,
    run,
    install_custom_scripts,
)
import conf

from slurmsync import sync_slurm

from setup_network_storage import (
    setup_network_storage,
    setup_nfs_exports,
)


log = logging.getLogger()


MOTD_HEADER = """
                                 SSSSSSS
                                SSSSSSSSS
                                SSSSSSSSS
                                SSSSSSSSS
                        SSSS     SSSSSSS     SSSS
                       SSSSSS               SSSSSS
                       SSSSSS    SSSSSSS    SSSSSS
                        SSSS    SSSSSSSSS    SSSS
                SSS             SSSSSSSSS             SSS
               SSSSS    SSSS    SSSSSSSSS    SSSS    SSSSS
                SSS    SSSSSS   SSSSSSSSS   SSSSSS    SSS
                       SSSSSS    SSSSSSS    SSSSSS
                SSS    SSSSSS               SSSSSS    SSS
               SSSSS    SSSS     SSSSSSS     SSSS    SSSSS
          S     SSS             SSSSSSSSS             SSS     S
         SSS            SSSS    SSSSSSSSS    SSSS            SSS
          S     SSS    SSSSSS   SSSSSSSSS   SSSSSS    SSS     S
               SSSSS   SSSSSS   SSSSSSSSS   SSSSSS   SSSSS
          S    SSSSS    SSSS     SSSSSSS     SSSS    SSSSS    S
    S    SSS    SSS                                   SSS    SSS    S
    S     S                                                   S     S
                SSS
                SSS
                SSS
                SSS
 SSSSSSSSSSSS   SSS   SSSS       SSSS    SSSSSSSSS   SSSSSSSSSSSSSSSSSSSS
SSSSSSSSSSSSS   SSS   SSSS       SSSS   SSSSSSSSSS  SSSSSSSSSSSSSSSSSSSSSS
SSSS            SSS   SSSS       SSSS   SSSS        SSSS     SSSS     SSSS
SSSS            SSS   SSSS       SSSS   SSSS        SSSS     SSSS     SSSS
SSSSSSSSSSSS    SSS   SSSS       SSSS   SSSS        SSSS     SSSS     SSSS
 SSSSSSSSSSSS   SSS   SSSS       SSSS   SSSS        SSSS     SSSS     SSSS
         SSSS   SSS   SSSS       SSSS   SSSS        SSSS     SSSS     SSSS
         SSSS   SSS   SSSS       SSSS   SSSS        SSSS     SSSS     SSSS
SSSSSSSSSSSSS   SSS   SSSSSSSSSSSSSSS   SSSS        SSSS     SSSS     SSSS
SSSSSSSSSSSS    SSS    SSSSSSSSSSSSS    SSSS        SSSS     SSSS     SSSS

"""
_MAINTENANCE_SBATCH_SCRIPT_PATH = dirs.custom_scripts / "perform_maintenance.sh"

def start_motd():
    """advise in motd that slurm is currently configuring"""
    wall_msg = "*** Slurm is currently being configured in the background. ***"
    motd_msg = MOTD_HEADER + wall_msg + "\n\n"
    Path("/etc/motd").write_text(motd_msg)
    util.run(f"wall -n '{wall_msg}'", timeout=30)


def end_motd(broadcast=True):
    """modify motd to signal that setup is complete"""
    Path("/etc/motd").write_text(MOTD_HEADER)

    if not broadcast:
        return

    run(
        "wall -n '*** Slurm {} setup complete ***'".format(lookup().instance_role),
        timeout=30,
    )
    if not lookup().is_controller:
        run(
            """wall -n '
/home on the controller was mounted over the existing /home.
Log back in to ensure your home directory is correct.
'""",
            timeout=30,
        )


def failed_motd():
    if lookup().is_hybrid_setup:
        #Do not modify motd for hybrid setup
        return
    """modify motd to signal that setup is failed"""
    wall_msg = f"*** Slurm setup failed! Please view log: {util.get_log_path()} ***"
    motd_msg = MOTD_HEADER + wall_msg + "\n\n"
    Path("/etc/motd").write_text(motd_msg)
    util.run(f"wall -n '{wall_msg}'", timeout=30)


def run_custom_scripts():
    """run custom scripts based on instance_role"""
    custom_dir = dirs.custom_scripts
    if lookup().is_controller:
        # controller has all scripts, but only runs controller.d
        custom_dirs = [custom_dir / "controller.d"]
    elif lookup().instance_role == "compute":
        # compute setup with compute.d and nodeset.d
        custom_dirs = [custom_dir / "compute.d", custom_dir / "nodeset.d"]
    elif lookup().is_login_node:
        # login setup with only login.d
        custom_dirs = [custom_dir / "login.d"]
    else:
        # Unknown role: run nothing
        custom_dirs = []
    custom_scripts = [
        p
        for d in custom_dirs
        for p in d.rglob("*")
        if p.is_file() and not p.name.endswith(".disabled")
    ]
    print_scripts = ",".join(str(s.relative_to(custom_dir)) for s in custom_scripts)
    log.debug(f"custom scripts to run: {custom_dir}/({print_scripts})")

    try:
        for script in custom_scripts:
            if "/controller.d/" in str(script):
                timeout = lookup().cfg.get("controller_startup_scripts_timeout", 300)
            elif "/compute.d/" in str(script) or "/nodeset.d/" in str(script):
                timeout = lookup().cfg.get("compute_startup_scripts_timeout", 300)
            elif "/login.d/" in str(script):
                timeout = lookup().cfg.get("login_startup_scripts_timeout", 300)
            else:
                timeout = 300
            timeout = None if not timeout or timeout < 0 else timeout
            log.info(f"running script {script.name} with timeout={timeout}")
            result = run(str(script), timeout=timeout, check=False, shell=True)
            runlog = (
                f"{script.name} returncode={result.returncode}\n"
                f"stdout={result.stdout}stderr={result.stderr}"
            )
            log.info(runlog)
            result.check_returncode()
    except OSError as e:
        log.error(f"script {script} is not executable")
        raise e
    except subprocess.TimeoutExpired as e:
        log.error(f"script {script} did not complete within timeout={timeout}")
        raise e
    except Exception as e:
        log.exception(f"script {script} encountered an exception")
        raise e

def mount_save_state_disk():
    disk_name = f"/dev/disk/by-id/google-{lookup().cfg.controller_state_disk.device_name}"
    mount_point = util.slurmdirs.state
    fs_type = "ext4"

    rdevice = util.run(f"realpath {disk_name}").stdout.strip()
    file_output = util.run(f"file -s {rdevice}").stdout.strip()
    if "filesystem" not in file_output:
        util.run(f"mkfs -t {fs_type} -q {rdevice}")

    fstab_entry = f"{disk_name} {mount_point} {fs_type}"
    with open("/etc/fstab", "r") as f:
        fstab = f.readlines()
    if fstab_entry not in fstab:
        with open("/etc/fstab", "a") as f:
            f.write(f"{fstab_entry} defaults 0 0\n")

    util.run(f"systemctl daemon-reload")

    os.makedirs(mount_point, exist_ok=True)
    util.run(f"mount {mount_point}")

    util.chown_slurm(mount_point)

def mount_munge_key_disk():
    state_disk_dir = "/var/spool/slurm/munge"
    mount_point = dirs.munge

    os.makedirs(state_disk_dir, exist_ok=True)

    util.run(f"mount --bind {state_disk_dir} {mount_point}")

    fstab_entry = f"{state_disk_dir} {mount_point}"
    with open("/etc/fstab", "r") as f:
        fstab = f.readlines()
    if fstab_entry not in fstab:
        with open("/etc/fstab", "a") as f:
            f.write(f"{fstab_entry} none bind 0 0\n")

    util.run(f"systemctl daemon-reload")

def setup_jwt_key():
    jwt_key = Path(slurmdirs.state / "jwt_hs256.key")

    if jwt_key.exists():
        log.info("JWT key already exists. Skipping key generation.")
    else:
        run("dd if=/dev/urandom bs=32 count=1 > " + str(jwt_key), shell=True)

    util.chown_slurm(jwt_key, mode=0o400)


def setup_munge_key():
    munge_key = Path(dirs.munge / "munge.key")

    if munge_key.exists():
        log.info("Munge key already exists. Skipping key generation.")
    else:
        run(f"dd if=/dev/random of={munge_key} bs=1024 count=1")

    shutil.chown(munge_key, user="munge", group="munge")
    os.chmod(munge_key, stat.S_IRUSR)
    run("systemctl restart munge", timeout=30)


def setup_nss_slurm():
    """install and configure nss_slurm"""
    # setup nss_slurm
    util.mkdirp(Path("/var/spool/slurmd"))
    run(
        "ln -s {}/lib/libnss_slurm.so.2 /usr/lib64/libnss_slurm.so.2".format(
            slurmdirs.prefix
        ),
        check=False,
    )
    run(r"sed -i 's/\(^\(passwd\|group\):\s\+\)/\1slurm /g' /etc/nsswitch.conf")


def setup_sudoers():
    content = """
# Allow SlurmUser to manage the slurm daemons
slurm ALL= NOPASSWD: /usr/bin/systemctl restart slurmd.service
slurm ALL= NOPASSWD: /usr/bin/systemctl restart sackd.service
slurm ALL= NOPASSWD: /usr/bin/systemctl restart slurmctld.service
"""
    sudoers_file = Path("/etc/sudoers.d/slurm")
    sudoers_file.write_text(content)
    sudoers_file.chmod(0o0440)


def setup_maintenance_script():
    perform_maintenance = """#!/bin/bash

#SBATCH --priority=low
#SBATCH --time=180

VM_NAME=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/name" -H "Metadata-Flavor: Google")
ZONE=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/zone" -H "Metadata-Flavor: Google" | cut -d '/' -f 4)

gcloud compute instances perform-maintenance $VM_NAME \
  --zone=$ZONE
"""


    with open(_MAINTENANCE_SBATCH_SCRIPT_PATH, "w") as f:
        f.write(perform_maintenance)

    util.chown_slurm(_MAINTENANCE_SBATCH_SCRIPT_PATH, mode=0o755)


def update_system_config(file, content):
    """Add system defaults options for service files"""
    sysconfig = Path("/etc/sysconfig")
    default = Path("/etc/default")

    if sysconfig.exists():
        conf_dir = sysconfig
    elif default.exists():
        conf_dir = default
    else:
        raise Exception("Cannot determine system configuration directory.")

    slurmd_file = Path(conf_dir, file)
    slurmd_file.write_text(content)


def configure_mysql():
    cnfdir = Path("/etc/my.cnf.d")
    if not cnfdir.exists():
        cnfdir = Path("/etc/mysql/conf.d")
    if not (cnfdir / "mysql_slurm.cnf").exists():
        (cnfdir / "mysql_slurm.cnf").write_text(
            """
[mysqld]
bind-address=127.0.0.1
innodb_buffer_pool_size=1024M
innodb_log_file_size=64M
innodb_lock_wait_timeout=900
"""
        )
    run("systemctl enable mariadb", timeout=30)
    run("systemctl restart mariadb", timeout=30)

    mysql = "mysql -u root -e"
    run(f"""{mysql} "drop user 'slurm'@'localhost'";""", timeout=30, check=False)
    run(f"""{mysql} "create user 'slurm'@'localhost'";""", timeout=30)
    run(
        f"""{mysql} "grant all on slurm_acct_db.* TO 'slurm'@'localhost'";""",
        timeout=30,
    )
    run(
        f"""{mysql} "drop user 'slurm'@'{lookup().control_host}'";""",
        timeout=30,
        check=False,
    )
    run(f"""{mysql} "create user 'slurm'@'{lookup().control_host}'";""", timeout=30)
    run(
        f"""{mysql} "grant all on slurm_acct_db.* TO 'slurm'@'{lookup().control_host}'";""",
        timeout=30,
    )


def configure_dirs():
    for p in dirs.values():
        util.mkdirp(p)

    for p in (dirs.slurm, dirs.scripts, dirs.custom_scripts):
        util.chown_slurm(p)

    for name, path in slurmdirs.items():
        util.mkdirp(path)
        if name != "prefix":
            util.chown_slurm(path)

    for sl, tgt in ( # create symlinks
        (Path("/etc/slurm"), slurmdirs.etc),
        (dirs.scripts / "etc", slurmdirs.etc),
        (dirs.scripts / "log", dirs.log),
    ):
        if sl.exists() and sl.is_symlink():
            sl.unlink()
        sl.symlink_to(tgt)

    for f in ("sort_nodes.py",): # copy auxiliary scripts
        #HYBRID-TODO Need this in the compute node, double check it
        #dst = Path(lookup().cfg.slurm_bin_dir) / f
        dst = Path(slurmdirs.prefix / "bin") / f
        shutil.copyfile(util.scripts_dir / f, dst)
        os.chmod(dst, 0o755)


def setup_controller():
    """Run controller setup"""
    log.info("Setting up controller")
    util.chown_slurm(dirs.scripts / "config.yaml", mode=0o600)
    install_custom_scripts()
    conf.gen_controller_configs(lookup())
    
    if lookup().cfg.controller_state_disk.device_name != None:
        mount_save_state_disk()
        mount_munge_key_disk()
    
    setup_jwt_key()
    setup_munge_key()
    setup_sudoers()
    setup_network_storage()

    run_custom_scripts()

    if not lookup().cfg.cloudsql_secret:
        configure_mysql()

    run("systemctl enable slurmdbd", timeout=30)
    run("systemctl restart slurmdbd", timeout=30)

    # Wait for slurmdbd to come up
    time.sleep(5)

    sacctmgr = f"{slurmdirs.prefix}/bin/sacctmgr -i"
    result = run(
        f"{sacctmgr} add cluster {lookup().cfg.slurm_cluster_name}", timeout=30, check=False
    )
    if "already exists" in result.stdout:
        log.info(result.stdout)
    elif result.returncode > 1:
        result.check_returncode()  # will raise error

    run("systemctl enable slurmctld", timeout=30)
    run("systemctl restart slurmctld", timeout=30)

    run("systemctl enable slurmrestd", timeout=30)
    run("systemctl restart slurmrestd", timeout=30)

    # Export at the end to signal that everything is up
    run("systemctl enable nfs-server", timeout=30)
    run("systemctl start nfs-server", timeout=30)

    setup_nfs_exports()
    run("systemctl enable --now slurmcmd.timer", timeout=30)

    log.info("Check status of cluster services")
    run("systemctl status munge", timeout=30)
    run("systemctl status slurmdbd", timeout=30)
    run("systemctl status slurmctld", timeout=30)
    run("systemctl status slurmrestd", timeout=30)

    sync_slurm()
    run("systemctl enable slurm_load_bq.timer", timeout=30)
    run("systemctl start slurm_load_bq.timer", timeout=30)
    run("systemctl status slurm_load_bq.timer", timeout=30)

    # Add script to perform maintenance
    setup_maintenance_script()

    log.info("Done setting up controller")
    pass


def setup_login():
    """run login node setup"""
    log.info("Setting up login")
    slurmctld_host = f"{lookup().control_host}"
    if lookup().control_addr:
        slurmctld_host = f"{lookup().control_host}({lookup().control_addr})"
    sackd_options = [
        f'--conf-server="{slurmctld_host}:{lookup().control_host_port}"',
    ]
    sysconf = f"""SACKD_OPTIONS='{" ".join(sackd_options)}'"""
    update_system_config("sackd", sysconf)
    install_custom_scripts()

    setup_network_storage()
    setup_sudoers()
    run("systemctl restart munge")
    run("systemctl enable sackd", timeout=30)
    run("systemctl restart sackd", timeout=30)
    run("systemctl enable --now slurmcmd.timer", timeout=30)

    run_custom_scripts()

    log.info("Check status of cluster services")
    run("systemctl status munge", timeout=30)
    run("systemctl status sackd", timeout=30)

    log.info("Done setting up login")

def _my_chown(path: Path, uid: int, gid: int,previous_uid: int = -1, previous_gid: int = -1):
    """
    If the current owner of the file at path is previous_uid change it to uid.
    The same goes for the group.
    """
    st = path.stat()
    my_uid = uid if (previous_uid == -1 or st.st_uid == previous_uid) else -1
    my_gid = gid if (previous_gid == -1 or st.st_gid == previous_gid) else -1
    if my_uid != -1 or my_gid != -1:
        os.chown(path,my_uid,my_gid)

def recursive_chown(path: Path, uid: int, gid: int,previous_uid: int = -1, previous_gid: int = -1):
    # Change ownership for the root directory
    _my_chown(path, uid, gid, previous_uid, previous_gid)

    # Walk through all subdirectories and files
    for root, dirs, files in os.walk(path):
        for directory in dirs:
            _my_chown(Path(os.path.join(root, directory)), uid, gid, previous_uid, previous_gid)
        for file in files:
            _my_chown(Path(os.path.join(root, file)), uid, gid, previous_uid, previous_gid)


def change_uid_gid_slurm():
    need_chown = False
    cur_gid = grp.getgrnam("slurm").gr_gid
    gid = lookup().cfg.hybrid_conf.slurm_gid
    if (cur_gid != gid):
        need_chown = True
        grc = run(f"groupmod -g {gid} slurm")
        if grc.returncode:
            log.error(f"Cannot change the gid of slurm rc={grc.returncode} stdout={grc.stdout} stderr={grc.stderr}")
            return

    cur_uid = pwd.getpwnam("slurm").pw_uid
    uid = lookup().cfg.hybrid_conf.slurm_uid
    if (cur_uid != uid):
        need_chown = True
        urc = run(f"usermod -u {uid} slurm")
        if urc.returncode:
            log.error(f"Cannot change the uid of slurm rc={urc.returncode} stdout={urc.stdout} stderr={urc.stderr}")
            return
    if need_chown:
        recursive_chown(slurmdirs.home, uid, gid)
        recursive_chown(slurmdirs.etc, uid, gid, cur_uid, cur_gid)
        recursive_chown(Path(lookup().cfg.slurm_log_dir), uid, gid, cur_uid, cur_gid)
        recursive_chown(dirs.slurm, uid, gid, cur_uid, cur_gid) #/slurm

def setup_compute():
    """run compute node setup"""
    log.info("Setting up compute")
    if lookup().cfg.hybrid:
        change_uid_gid_slurm()
    util.chown_slurm(dirs.scripts / "config.yaml", mode=0o600)
    slurmctld_host = f"{lookup().control_host}"
    if lookup().control_addr:
        slurmctld_host = f"{lookup().control_host}({lookup().control_addr})"
    slurmd_options = [
        f'--conf-server="{slurmctld_host}:{lookup().control_host_port}"',
    ]

    try:
        slurmd_feature = util.instance_metadata("attributes/slurmd_feature")
    except Exception:
        # TODO: differentiate between unset and error
        slurmd_feature = None

    if slurmd_feature is not None:
        slurmd_options.append(f'--conf="Feature={slurmd_feature}"')
        slurmd_options.append("-Z")

    sysconf = f"""SLURMD_OPTIONS='{" ".join(slurmd_options)}'"""
    update_system_config("slurmd", sysconf)
    install_custom_scripts()

    setup_nss_slurm()
    setup_network_storage()

    has_gpu = run("lspci | grep --ignore-case 'NVIDIA' | wc -l", shell=True).returncode
    if has_gpu:
        run("nvidia-smi")

    run_custom_scripts()

    setup_sudoers()
    run("systemctl restart munge", timeout=30)
    run("systemctl enable slurmd", timeout=30)
    run("systemctl restart slurmd", timeout=30)
    run("systemctl enable --now slurmcmd.timer", timeout=30)

    log.info("Check status of cluster services")
    run("systemctl status munge", timeout=30)
    run("systemctl status slurmd", timeout=30)

    log.info("Done setting up compute")

def setup_cloud_ops() -> None:
    """add deployment info to cloud ops config"""
    cloudOpsStatus = run(
        "systemctl is-active --quiet google-cloud-ops-agent.service", check=False
    ).returncode
    
    if cloudOpsStatus != 0:
        return

    with open("/etc/google-cloud-ops-agent/config.yaml", "r") as f:
        file = yaml.safe_load(f)

    cluster_info = {
        'type':'modify_fields',
        'fields': {
            'labels."cluster_name"':{
                'static_value':f"{lookup().cfg.slurm_cluster_name}"
            },
            'labels."hostname"':{
                'static_value': f"{lookup().hostname}"
            }
        }
    }

    file["logging"]["processors"]["add_cluster_info"] = cluster_info
    file["logging"]["service"]["pipelines"]["slurmlog_pipeline"]["processors"].append("add_cluster_info")
    file["logging"]["service"]["pipelines"]["slurmlog2_pipeline"]["processors"].append("add_cluster_info")

    with open("/etc/google-cloud-ops-agent/config.yaml", "w") as f:
        yaml.safe_dump(file, f, sort_keys=False)

    run("systemctl restart google-cloud-ops-agent.service", timeout=30)

def get_config(bucket:str = None):
    sleep_seconds = 5
    while True:
        try:
            _, cfg = util.fetch_config(bucket=bucket)
            util.update_config(cfg)
            if bucket is not None:
                lookup().hybrid_setup = True
            break
        except util.DeffetiveStoredConfigError as e:
            log.warning(f"config is not ready yet: {e}, sleeping for {sleep_seconds}s")
        except Exception as e:
            log.exception(f"unexpected error while fetching config, sleeping for {sleep_seconds}s")
        time.sleep(sleep_seconds)
    log.info("Config fetched")

def setup_hybrid(bucket: str): #HYBRID-TODO review this
    log.info("Starting hybrid setup, fetching config")
    get_config(bucket)
    log.info("Generating the config files")
    conf.gen_controller_configs(lookup())
    log.info("Success")

def main():
    start_motd()

    log.info("Starting setup, fetching config")
    get_config()
    setup_cloud_ops()
    configure_dirs()
    # call the setup function for the instance type
    {
        "controller": setup_controller,
        "compute": setup_compute,
        "login": setup_login,
    }.get(
        lookup().instance_role,
        lambda: log.fatal(f"Unknown node role: {lookup().instance_role}"))()

    end_motd()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slurmd-feature", dest="slurmd_feature", help="Unused, to be removed.")
    parser.add_argument("--hybrid", dest="hybrid", action="store_true", help="Do the hybrid setup.")
    parser.add_argument("--bucket", dest="bucket", help="The bucket URI where config.yaml is.")
    args = util.init_log_and_parse(parser)

    try:
        if args.hybrid:
            setup_hybrid(args.bucket)
        else:
            main()
    except subprocess.TimeoutExpired as e:
        stdout = (e.stdout or b"").decode().strip()
        stderr = (e.stderr or b"").decode().strip()

        log.error(
            f"""TimeoutExpired:
    command={e.cmd}
    timeout={e.timeout}
    stdout:
{stdout}
    stderr:
{stderr}
"""
        )
        log.error("Aborting setup...")
        failed_motd()
    except subprocess.CalledProcessError as e:
        log.error(
            f"""CalledProcessError:
    command={e.cmd}
    returncode={e.returncode}
    stdout:
{e.stdout.strip()}
    stderr:
{e.stderr.strip()}
"""
        )
        log.error("Aborting setup...")
        failed_motd()
    except Exception:
        log.exception("Aborting setup...")
        failed_motd()
