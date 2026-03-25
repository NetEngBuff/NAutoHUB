import os
import yaml
import shutil
import sys
import time
import docker
import json
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    stream_with_context,
    Response,
)
from jinja2 import Environment, FileSystemLoader
import subprocess
from threading import Thread
from pathlib import Path
import asyncio
import netifaces


# Get the current directory of this script
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))

# Go up two levels and into the 'python-files' directory
python_files_dir = os.path.join(current_dir, "..", "..", "python-files")
predict_dir = os.path.join(current_dir, "..", "..", "machine_learning", "predict")
helper_dir = os.path.join(current_dir, "..", "..", "machine_learning", "helper")
templates_dir = os.path.join(current_dir, "..", "..", "templates")
pilot_config_dir = os.path.join(project_root, "pilot-config")
topology_dir = os.path.join(project_root, "NSOT", "topology")

# Add 'python-files' to the system path
sys.path.append(os.path.abspath(python_files_dir))
sys.path.append(os.path.abspath(helper_dir))
sys.path.append(os.path.abspath(predict_dir))
topo_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../pilot-config/topo.yml")
)


# Import your custom modules from 'python-files'
from create_hosts import write_hosts_csv
from ping import ping_local, ping_remote
from goldenConfig import generate_configs
from show_commands import execute_show_command
from generate_yaml import create_yaml_from_form_data
from config_Gen import conf_gen
from update_topo import update_topology, get_hosts_from_csv
from dhcp_updates import configure_dhcp_relay, configure_dhcp_server
from update_hosts import update_hosts_csv, regenerate_hosts_csv
from git_jenkins import push_and_monitor_jenkins
from push_config import push_configuration
from push_uploaded_config import push_uploaded_config
from config_backup import rollback_to_golden_config
from read_IPAM import IPAMReader
from read_hosts import HostsReader
from clab_builder import build_clab_topology
from clab_push import get_docker_images
from ollama_utils import stop_ollama_model
from gnmi_hosts import update_gnmic_yaml_from_hosts

# File path for IPAM CSV file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IPAM_DIR = os.path.join(BASE_DIR, "..", "..", "IPAM")
PILOT_DIR = os.path.join(BASE_DIR, "..", "..", "..", "pilot-config")
ipam_file_path = os.path.join(IPAM_DIR, "ipam_output.csv")

# Initialize
ipam_reader = IPAMReader(file_path=ipam_file_path, update_interval=10)
hosts_reader = HostsReader(BASE_DIR)

app = Flask(__name__)

# Set up Jinja2 environment to load templates from 'NSOT/templates' folder
env = Environment(loader=FileSystemLoader(templates_dir))

# Context processor to make devices available in all templates
@app.context_processor
def inject_devices():
    try:
        devices = hosts_reader.get_devices()
        return dict(devices=devices)
    except Exception as e:
        print(f"Error loading devices for context: {e}")
        return dict(devices=[])


@app.route("/")
def homepage():
    devices = hosts_reader.get_devices()
    return render_template("homepage.html", devices=devices)


@app.route("/chat-query", methods=["POST"])
def chat_query():
    data = request.json
    user_input = data.get("message")

    def generate_sync():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def inner():
            # Step 1: Smalltalk detection
            smalltalk_keywords = [
                "hi",
                "hello",
                "thanks",
                "thank you",
                "bye",
                "who are you",
                "goodbye",
            ]
            if any(kw in user_input.lower() for kw in smalltalk_keywords):
                yield "👋 Hi there! I'm NBot, your friendly network assistant."
                return

            import ollama

            response = ollama.chat(
                model="llama3.1",
                messages=[
                    {
                        "role": "system",
                        "content": """You are an intelligent, helpful network automation assistant. 
If the user's input is a casual greeting, question about yourself, or a non-technical sentence, reply only with 'SMALLTALK'. 
If the user's input is technical (related to networking, configs, interfaces, protocols, etc), reply only with 'TECHNICAL'.""",
                    },
                    {"role": "user", "content": user_input},
                ],
            )

            mode = response["message"]["content"].strip()
            if mode == "SMALLTALK":
                yield "🧠 Hello! How can I assist with your network today?"
                return
            elif mode != "TECHNICAL":
                yield "⚠️ I couldn't determine if this was a technical query. Please try rephrasing."
                return

            # Step 2: LLM extraction and response
            from llm_extract import real_llm_extract, process_cli_output
            from predict_specific import predict_specific_output
            from predict_genericshow import predict_generic_show_command
            from fetch_show import connect_and_run_command
            from generate_show import generate_show_command
            from generate_config import render_device_config

            extracted_actions = real_llm_extract(user_input)
            if not extracted_actions:
                yield "⚠️ Sorry, could not understand the request."
                return

            for action in extracted_actions:
                intent = action.get("intent")
                device = action.get("device")
                monitor = action.get("monitor")
                configure = action.get("configure")

                if (configure is None or configure == {}) and monitor is None:
                    if intent is None:
                        yield "⚠️ Intent is missing."
                        return

                    cli_command = predict_generic_show_command(intent)
                    cli_output = connect_and_run_command(device, cli_command)

                    if cli_output:
                        answer = process_cli_output(user_input, cli_output)
                        for token in answer:
                            yield token
                    else:
                        yield "⚠️ No output from device."

                elif configure is None or configure == {}:
                    predicted_show_type = predict_specific_output(intent)
                    final_command = generate_show_command(predicted_show_type, monitor)
                    cli_output = connect_and_run_command(device, final_command)

                    if cli_output:
                        answer = process_cli_output(user_input, cli_output)
                        for token in answer:
                            yield token
                    else:
                        yield "⚠️ No output from device."

                elif monitor is None:
                    predicted_template = predict_specific_output(intent)

                    if isinstance(configure, dict):
                        params = configure
                    else:
                        params = {"raw": configure}

                    config_text = render_device_config(
                        device, predicted_template, params
                    )

                    if config_text:
                        yield f"✅ Configuration generated for {device}:\n\n{config_text}"
                    else:
                        yield "⚠️ Failed to generate configuration."

        async_gen = inner()
        while True:
            try:
                token = loop.run_until_complete(async_gen.__anext__())
                yield token
            except StopAsyncIteration:
                break

    return Response(
        stream_with_context(generate_sync()), content_type="text/event-stream"
    )


@app.route("/shutdown-ollama", methods=["POST"])
def shutdown_ollama_route():
    try:
        stop_ollama_model("llama3.1")
        return jsonify({"status": "success", "message": "Ollama stopped."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/add-hosts", methods=["GET", "POST"])
def add_hosts():
    message = None
    if request.method == "POST":
        hostnames = request.form.getlist("hostname[]")
        usernames = request.form.getlist("username[]")
        passwords = request.form.getlist("password[]")
        management_ips = request.form.getlist("management_ip[]")
        subnet_cidrs = request.form.getlist("subnet_cidr[]")
        save_mode = request.form.get("save_mode", "new")

        rows = []
        for i in range(len(hostnames)):
            if hostnames[i] and usernames[i] and passwords[i] and management_ips[i] and subnet_cidrs[i]:
                rows.append(
                    [hostnames[i], usernames[i], passwords[i], management_ips[i], subnet_cidrs[i]]
                )

        if rows:
            path = write_hosts_csv(rows, append=(save_mode == "append"))
            mode_label = "Appended to" if save_mode == "append" else "Created"
            message = f"✅ {mode_label} hosts.csv with {len(rows)} new device(s)."
        else:
            message = "⚠️ No valid entries to save."
            

    return render_template("add_hosts.html", message=message)


@app.route("/build-topology", methods=["GET", "POST"])
def build_topology():
    if request.method == "POST" and "generate" in request.form:
        topo_name = request.form.get("topo_name", "custom_topo")
        devices = []
        links = []

        # ✅ Collect device entries
        i = 0
        while True:
            name = request.form.get(f"device_name_{i}")
            if not name:
                break

            kind = request.form.get(f"device_kind_{i}")
            image = request.form.get(f"device_image_{i}")
            config = request.form.get(f"device_config_{i}")
            exec_lines = request.form.getlist(f"device_exec_{i}[]")
            ip_with_subnet = request.form.get(f"device_mgmt_ip_{i}", "")
            ip_address = (
                ip_with_subnet.split("/")[0]
                if "/" in ip_with_subnet
                else ip_with_subnet
            )
            username = request.form.get(f"device_username_{i}", "")
            password = request.form.get(f"device_password_{i}", "")

            devices.append(
                {
                    "name": name,
                    "kind": kind,
                    "image": image,
                    "config": config,
                    "exec": exec_lines,
                    "mgmt_ip": ip_with_subnet,
                    "ip_address": ip_address,
                    "username": username,
                    "password": password,
                }
            )

            i += 1

        # ✅ Parse links
        link_dev1_list = request.form.get("link_dev1_json")
        link_dev2_list = request.form.get("link_dev2_json")
        if link_dev1_list and link_dev2_list:
            dev1_list = json.loads(link_dev1_list)
            dev2_list = json.loads(link_dev2_list)
            links = list(zip(dev1_list, dev2_list))

        # ✅ Build topology and update CSV
        print("[INFO] Generating topology YAML...")
        output_path = build_clab_topology(topo_name, devices, links)
        print(f"[✔] YAML saved at: {output_path}")

        print("[INFO] Generating hosts.csv...")
        regenerate_hosts_csv(devices)

        # ✅ Render response
        client = docker.from_env()
        images = [tag for img in client.images.list() for tag in img.tags if ":" in tag]
        message = f"✅ topo.yml generated at: <code>{output_path}</code>"

        return render_template(
            "build_topology.html", docker_images=images, message=message
        )

    # GET fallback
    client = docker.from_env()
    images = [tag for img in client.images.list() for tag in img.tags if ":" in tag]
    return render_template("build_topology.html", docker_images=images)


@app.route("/deploy-topology", methods=["POST"], endpoint="deploy_topology_route")
def deploy_topology_route():
    yaml_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "pilot-config", "topo.yml"
        )
    )
    
    print("[INFO] Destroying old topology...")
    # Using result.run with capture_output=True to keep console clean
    subprocess.run(f"sudo containerlab destroy -t {yaml_path}", shell=True, capture_output=True, text=True)

    # Cleanup directory
    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f) or {}
        lab_name = data.get("name", "unknown")
        lab_dir = Path(yaml_path).parent / f"clab-{lab_name}"
        if lab_dir.exists() and lab_dir.is_dir():
            shutil.rmtree(lab_dir)
            print(f"[✔] Deleted old lab folder: {lab_dir}")
    except Exception as e:
        print(f"[ℹ] Lab folder cleanup skipped: {e}")

    print("[INFO] Deploying new topology...")
    try:
        # We capture output to prevent the "messy" terminal logs you saw earlier
        result = subprocess.run(
            f"sudo containerlab deploy -t {yaml_path}",
            shell=True,
            capture_output=True,
            text=True,
            check=True
        )
        
        deploy_output = result.stdout
        time.sleep(2)
        update_gnmic_yaml_from_hosts()
        
        # System services still require sudo, ensure NOPASSWD is set in sudoers
        subprocess.run(["sudo", "systemctl", "restart", "gnmic_nautohub.service"], check=True)
        subprocess.run(["sudo", "systemctl", "restart", "ipam.service"], check=True)
        
        print("[✔] Deploy output captured successfully.")
        message = "✅ Containerlab topology deployed successfully."

    except subprocess.CalledProcessError as e:
        # e.stderr or e.stdout contains the reason for failure (like "requires root privileges")
        error_detail = e.stderr if e.stderr else e.stdout
        print(f"[ERROR] Deployment failed: {error_detail}")
        message = f"❌ Failed to deploy topology:<br><pre>{error_detail}</pre>"

    return render_template(
        "build_topology.html", docker_images=get_docker_images(), message=message
    )


@app.route("/delete-topology", methods=["POST"], endpoint="delete_topology_route")
def delete_topology_route():
    yaml_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "pilot-config", "topo.yml"
        )
    )
    print("[INFO] Deleting topology...")
    try:
        result = subprocess.run(
            f"sudo containerlab destroy -t {yaml_path}",
            shell=True,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Re-verify lab name for folder cleanup
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        lab_name = data.get("name", "unknown")
        lab_dir = Path(yaml_path).parent / f"clab-{lab_name}"
        
        if lab_dir.exists() and lab_dir.is_dir():
            shutil.rmtree(lab_dir)

        message = "✅ Topology deleted successfully."
        print("[✔] Topology destroyed and folder cleaned.")

    except subprocess.CalledProcessError as e:
        error_detail = e.stderr if e.stderr else e.stdout
        print(f"[ERROR] Delete failed: {error_detail}")
        message = f"❌ Failed to delete topology:<br><pre>{error_detail}</pre>"

    return render_template(
        "build_topology.html", docker_images=get_docker_images(), message=message
    )


@app.route("/add-device", methods=["GET", "POST"])
def add_device():
    message = None

    if request.method == "POST":
        device_name = request.form["device_name"]
        kind = request.form["kind"]
        image = request.form["image"]
        config = request.form.get("config", "")
        exec_lines = request.form.getlist("exec[]")
        mac_address = request.form.get("mac_address", "")
        ip_with_subnet = request.form.get("ip_address", "")
        ip_address = ip_with_subnet.split("/")[0]
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        connection_count = int(request.form.get("connection_count", "0"))

        # Optional DHCP relay values
        relay_toggle = request.form.get("relay_toggle")
        connected_ip = request.form.get("connected_ip")
        helper_ip = request.form.get("helper_ip")
        dhcp_server = request.form.get("dhcp_server")
        new_subnet = request.form.get("new_subnet")
        range_lower = request.form.get("range_lower")
        range_upper = request.form.get("range_upper")
        default_gateway = request.form.get("default_gateway")

        connect_to = [
            request.form.get(f"connect_to_{i}")
            for i in range(connection_count)
            if request.form.get(f"connect_to_{i}")
        ]

        topo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../../pilot-config/topo.yml")
        )
        print("[INFO] Destroying old topology before update...")
        os.system(f"sudo containerlab destroy -t {topo_path} || true")

        try:
            update_topology(
                topo_path=topo_path,
                device_name=device_name,
                kind=kind,
                image=image,
                config=config,
                exec_lines=exec_lines,
                mac=mac_address,
                connect_to_list=connect_to,
                mgmt_ip=ip_with_subnet,
                username=username,
                password=password,
            )

            update_hosts_csv(
                device_name, ip_address, username=username, password=password
            )

            print("[INFO] Deploying new topology...")
            clab_path = os.path.join(PILOT_DIR, "clab-example")
            if os.path.exists(clab_path):
                shutil.rmtree(clab_path)
                print(f"✅ Removed: {clab_path}")
            else:
                print(f"⚠️ Path does not exist, skipping: {clab_path}")

            deploy_output = subprocess.check_output(
                f"sudo containerlab deploy -t {topo_path}",
                shell=True,
                stderr=subprocess.STDOUT,
                text=True,
            )
            time.sleep(2)
            update_gnmic_yaml_from_hosts()
            subprocess.run(
                ["sudo", "systemctl", "restart", "gnmic_nautohub.service"], check=True
            )
            subprocess.run(["sudo", "systemctl", "restart", "ipam.service"], check=True)
            print("[✔] Deploy output:")
            print(deploy_output)

            if relay_toggle:
                configure_dhcp_relay(
                    connected_device=connect_to[0] if connect_to else "",
                    connected_interface="eth1",
                    connected_ip=connected_ip,
                    helper_ip=helper_ip,
                )
                configure_dhcp_server(
                    mac_address,
                    dhcp_server,
                    new_subnet,
                    range_lower,
                    range_upper,
                    default_gateway,
                    ip_address,
                )

            message = "✅ Topology deployed successfully."

        except subprocess.CalledProcessError as e:
            print("[ERROR] Deployment failed:")
            print(e.output)
            message = f"❌ Deployment failed:<br><pre>{e.output}</pre>"

    docker_images = [
        tag for img in docker.from_env().images.list() for tag in img.tags if ":" in tag
    ]
    return render_template(
        "add_device.html",
        docker_images=docker_images,
        available_hosts=get_hosts_from_csv(),
        message=message,
    )


@app.route("/configure-device", methods=["GET", "POST"])
def configure_device():
    try:
        devices = hosts_reader.get_devices()
        if request.method == "POST":
            device_id = request.form.get("device_id")
            device_vendor = request.form.get("device_vendor")

            # Interfaces
            interfaces = []
            for i_type, i_num, ip, mask, sp in zip(
                request.form.getlist("interface_type[]"),
                request.form.getlist("interface_number[]"),
                request.form.getlist("interface_ip[]"),
                request.form.getlist("interface_mask[]"),
                request.form.getlist("switchport[]"),
            ):
                interfaces.append(
                    {
                        "type": i_type,
                        "number": i_num,
                        "ip": ip if sp != "yes" else None,
                        "mask": mask if sp != "yes" else None,
                        "switchport": sp == "yes",
                    }
                )

            # Subinterfaces
            subinterfaces = []
            for parent, sid, vlan, ip, mask in zip(
                request.form.getlist("subinterface_parent[]"),
                request.form.getlist("subinterface_id[]"),
                request.form.getlist("subinterface_vlan[]"),
                request.form.getlist("subinterface_ip[]"),
                request.form.getlist("subinterface_mask[]"),
            ):
                subinterfaces.append(
                    {"parent": parent, "id": sid, "vlan": vlan, "ip": ip, "mask": mask}
                )

            # VLANs
            vlans = []
            for vlan_id, vlan_name in zip(
                request.form.getlist("vlan_id[]"),
                request.form.getlist("vlan_name[]"),
            ):
                vlans.append({"id": vlan_id, "name": vlan_name})

            # RIP
            rip = None
            rip_versions = request.form.getlist("rip_version[]")
            rip_networks = request.form.getlist("rip_network[]")
            rip_redistribute_selected = request.form.get("rip_redistribute")
            rip_bgp_as = request.form.getlist("rip_bgp_as[]")
            rip_bgp_metric = request.form.getlist("rip_bgp_metric[]")

            if rip_versions:
                rip = {
                    "version": rip_versions[0],
                    "networks": [{"ip": net} for net in rip_networks if net],
                }

                if rip_redistribute_selected:
                    redistribute = {}
                    if rip_bgp_as and rip_bgp_as[0]:
                        redistribute["as_number"] = rip_bgp_as[0]
                    if rip_bgp_metric and rip_bgp_metric[0]:
                        redistribute["metric"] = int(rip_bgp_metric[0])
                    if redistribute:
                        rip["redistribute"] = redistribute

            # OSPF
            ospf = None
            ospf_process_ids = request.form.getlist("ospf_process_id[]")
            ospf_networks = request.form.getlist("ospf_network[]")
            ospf_wildcards = request.form.getlist("ospf_wildcard[]")
            ospf_areas = request.form.getlist("ospf_area[]")
            ospf_redistribute_connected = request.form.getlist(
                "ospf_redistribute_connected[]"
            )
            ospf_redistribute_bgp = request.form.getlist("ospf_redistribute_bgp[]")

            ospf_process_ids = [pid for pid in ospf_process_ids if pid.strip()]
            if ospf_process_ids:
                ospf = {
                    "process_id": ospf_process_ids[0],
                    "networks": [
                        {
                            "ip": ospf_networks[i],
                            "wildcard": ospf_wildcards[i],
                            "area": ospf_areas[i],
                        }
                        for i in range(len(ospf_networks))
                    ],
                    "redistribute_connected": len(ospf_redistribute_connected) > 0,
                    "redistribute_bgp": len(ospf_redistribute_bgp) > 0,
                }

            # BGP
            bgp = None
            bgp_asn = request.form.get("bgp_asn")
            bgp_networks = request.form.getlist("bgp_network[]")
            bgp_masks = request.form.getlist("bgp_mask[]")
            bgp_neighbors = request.form.getlist("bgp_neighbor[]")
            bgp_remote_as = request.form.getlist("bgp_remote_as[]")
            bgp_address_families = request.form.getlist("bgp_address_family[]")

            # NEW: Read redistribute toggles from BGP section
            redistribute_ospf_into_bgp = "redistribute_ospf_into_bgp" in request.form
            redistribute_rip_into_bgp = "redistribute_rip_into_bgp" in request.form

            if bgp_asn and bgp_address_families:
                address_family_entries = {}

                for af, net, mask, neighbor_ip, neighbor_as in zip(
                    bgp_address_families,
                    bgp_networks,
                    bgp_masks,
                    bgp_neighbors,
                    bgp_remote_as,
                ):
                    if not (af and net and mask and neighbor_ip and neighbor_as):
                        continue

                    if af not in address_family_entries:
                        address_family_entries[af] = {
                            "type": af,
                            "networks": [],
                            "neighbors": [],
                        }

                    address_family_entries[af]["networks"].append(
                        {"ip": net, "mask": mask}
                    )
                    address_family_entries[af]["neighbors"].append(
                        {"ip": neighbor_ip, "remote_as": neighbor_as}
                    )

                bgp = {
                    "as_number": bgp_asn,
                    "address_families": list(address_family_entries.values()),
                    "redistribute_ospf": redistribute_ospf_into_bgp,
                    "redistribute_rip": redistribute_rip_into_bgp,
                }

            # Attempt to generate YAML and push via Jenkins
            try:
                create_yaml_from_form_data(
                    device_id=device_id,
                    device_vendor=device_vendor,
                    interfaces=interfaces,
                    subinterfaces=subinterfaces,
                    vlans=vlans,
                    rip=rip,
                    ospf=ospf,
                    bgp=bgp,
                )
                conf_gen()
                jenkins_result = push_and_monitor_jenkins()

                if jenkins_result == "SUCCESS":
                    return render_template(
                        "configure_device.html",
                        jenkins_result="jenkins_success",
                        device_id=device_id,
                        message="✅ Jenkins pipeline succeeded!",
                    )
                else:
                    return render_template(
                        "configure_device.html",
                        jenkins_result="jenkins_failure",
                        device_id=device_id,
                        message="❌ Jenkins pipeline failed.",
                    )

            except Exception as pipeline_error:
                print("🔥 Pipeline error:", pipeline_error)
                return render_template(
                    "configure_device.html",
                    jenkins_result="jenkins_failure",
                    device_id=device_id,
                    message=str(pipeline_error),
                )

        return render_template(
            "configure_device.html", jenkins_result=None, devices=devices
        )

    except Exception as e:
        print(f"Error in /configure-device: {e}")
        return render_template(
            "configure_device.html",
            jenkins_result="jenkins_failure",
            device_id="unknown",
            message=str(e),
            devices=[],
        )


@app.route("/push-config", methods=["POST"])
def push_config():
    data = request.get_json()
    device_id = data.get("device_id")

    # Run push_configuration function
    push_status = push_configuration(device_id)

    if "successfully" in push_status:
        return jsonify({"status": "success", "message": push_status})
    else:
        return jsonify({"status": "error", "message": push_status})


@app.route("/upload-config", methods=["POST"])
def upload_config():
    """
    Handle uploaded configuration file and push to device using Netmiko
    """
    try:
        # Get form data
        device_id = request.form.get("device_id")
        device_vendor = request.form.get("device_vendor")
        config_file = request.files.get("config_file")

        # Validate inputs
        if not device_id or not device_vendor:
            return jsonify(
                {"status": "error", "message": "Device ID and vendor are required"}
            )

        if not config_file:
            return jsonify({"status": "error", "message": "No config file provided"})

        # Read file content
        config_content = config_file.read().decode("utf-8")

        if not config_content.strip():
            return jsonify({"status": "error", "message": "Config file is empty"})

        # Push configuration using Netmiko
        success, message = push_uploaded_config(device_id, device_vendor, config_content)

        if success:
            return jsonify({"status": "success", "message": message})
        else:
            return jsonify({"status": "error", "message": message})

    except Exception as e:
        print(f"Error in /upload-config: {e}")
        return jsonify({"status": "error", "message": f"Error processing upload: {str(e)}"})


@app.route("/rollback", methods=["POST"])
def rollback_device():
    """
    Rollback a device to its golden configuration
    """
    try:
        data = request.get_json()
        device_id = data.get("device_id")
        device_vendor = data.get("device_vendor")

        if not device_id or not device_vendor:
            return jsonify(
                {"status": "error", "message": "Device ID and vendor are required"}
            )

        # Perform rollback
        success, message = rollback_to_golden_config(device_id, device_vendor)

        if success:
            return jsonify({"status": "success", "message": message})
        else:
            return jsonify({"status": "error", "message": message})

    except Exception as e:
        print(f"Error in /rollback: {e}")
        return jsonify({"status": "error", "message": f"Rollback error: {str(e)}"})


@app.route("/tools", methods=["GET", "POST"])
def tools():
    ping_result = None
    config_result = None
    show_result = None

    # Fetch devices dynamically
    devices = hosts_reader.get_devices()

    # Handling Ping Test
    if (
        request.method == "POST"
        and "source" in request.form
        and "destination" in request.form
    ):
        source = request.form["source"]
        destination = request.form["destination"]

        if source == "localhost":
            success, output = ping_local(destination)
        else:
            username = request.form.get("username", "root")
            password = request.form.get("password", "password")
            success, output = ping_remote(source, destination, username, password)

        if success:
            ping_result = f'<span style="color:green;">Ping successful!</span><br><pre>{output}</pre>'
        else:
            ping_result = (
                f'<span style="color:red;">Ping failed.</span><br><pre>{output}</pre>'
            )

    # Handling Golden Config Generator
    if request.method == "POST" and (
        "device" in request.form or "select_all" in request.form
    ):
        select_all = request.form.get("select_all", "off")
        hostname = request.form.get("device")

        if select_all == "on":
            filenames = generate_configs(select_all=True)
        elif hostname:
            filenames = generate_configs(select_all=False, hostname=hostname)

        if filenames:
            config_result = f"<h3>Generated Config Files:</h3><ul>"
            for file in filenames:
                config_result += f"<li>{file}</li>"
            config_result += "</ul>"

    if request.method == "POST" and (
        "selected_device" in request.form
        and (
            any(key.endswith("-dropdown") for key in request.form)
            or "command" in request.form
        )
    ):

        hostname = request.form.get("selected_device")
        selected_command = request.form.get("command", "")

        if not selected_command:
            for key in request.form:
                if key.endswith("-dropdown"):
                    selected_command = request.form[key]
                    break

        success, result = execute_show_command(hostname, selected_command)
        print(result)
        show_result = (
            f"<h3>Command Output:</h3><pre>{result}</pre>"
            if success
            else f'<span style="color:red;">Command failed: {result}</span>'
        )

    return render_template(
        "tools.html",
        ping_result=ping_result,
        config_result=config_result,
        devices=devices,
        show_result=show_result,
    )


@app.route("/ipam")
def ipam():
    """Route to display IPAM table."""
    # print(f"Rendering IPAM table with data: {ipam_reader.ipam_data}")  # Debug statement
    return render_template("ipam.html", ipam_data=ipam_reader.ipam_data)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/dashboard")
def dashboard():
    # Embed your Grafana dashboard in the dashboard template
    return render_template("dashboard.html")


def run_deployment_and_relay_config(
    deploy_command,
    relay_toggle,
    connected_device,
    connected_interface,
    connected_ip,
    helper_ip,
    mac_address,
    dhcp_server,
    new_subnet,
    range_lower,
    range_upper,
    default_gateway,
    ip_address,
):
    # Run deployment synchronously in the thread
    deploy_result = subprocess.run(deploy_command, shell=True)

    # Only proceed with DHCP configuration if the deployment was successful
    if deploy_result.returncode == 0 and relay_toggle:
        configure_dhcp_relay(
            connected_device, connected_interface, connected_ip, helper_ip
        )
        configure_dhcp_server(
            mac_address,
            dhcp_server,
            new_subnet,
            range_lower,
            range_upper,
            default_gateway,
            ip_address,
        )


@app.route("/topology")
def topology():
    try:
        subprocess.Popen(
            f"sudo containerlab graph -t {topo_path}",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"[INFO] Started containerlab graph for: {topo_path}")
    except Exception as e:
        print(f"[ERROR] Failed to start containerlab graph: {e}")

    try:
        gws = netifaces.gateways()
        default_iface = gws["default"][netifaces.AF_INET][1]
        iface_addrs = netifaces.ifaddresses(default_iface)
        interface_ip = iface_addrs[netifaces.AF_INET][0]["addr"]
    except Exception as e:
        print(f"[ERROR] Could not determine interface IP: {e}")
        interface_ip = "127.0.0.1"

    graph_url = f"http://{interface_ip}:50080"
    return render_template("topology.html", graph_url=graph_url)


import docker


@app.route("/clab-health")
def clab_health():
    try:
        client = docker.from_env()
        containers = client.containers.list(filters={"label": "containerlab"})
        if containers:
            return jsonify({"status": "up", "message": "Containerlab is up"})
        else:
            return jsonify({"status": "down", "message": "Containerlab is down"})
    except Exception as e:
        return jsonify({"status": "down", "message": f"Error: {str(e)}"})


if __name__ == "__main__":
    thread = Thread(target=ipam_reader.read_ipam_file, daemon=True)
    thread.start()
    app.run(host="0.0.0.0", port=5555, debug=True, threaded=True)
