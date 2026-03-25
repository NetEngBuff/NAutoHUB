---
# What is NAutoHUB?

NAutoHUB is an NMAS – Network Management and Automation System – designed to simplify network configuration, monitoring, and automation.
It also functions as the Network Source of Truth (NSoT) by maintaining a centralized, version-controlled repository of device configurations, IP allocations, templates, telemetry, and state data.

![Architecture](pictures/nhub-arch.jpeg)

# What is NSOT?

A Network Source of Truth provides a single, reliable reference for all network data — configurations, states, IPs, and inventory. 

NSOT is the core of NAutoHUB. It includes:
 - GUI/ – Web-based interface to manage network devices
 - python-files/ – Scripts for config generation, deployment, and automation
 - golden_configs/ – Pre-validated configuration templates
 - golden_states/ – data captures of ideal device states
 - IPAM/ – IP Address Management and device inventory
 - templates/ – Jinja2 templates for building device configs
 - datalake/ – Storage for SNMP/gNMI telemetry and performance metrics


# Why CI/CD?

CI/CD pipelines are the foundation for implementing Infrastructure as Code (IaC), allowing automated, consistent, and reliable network deployments from development to production.
![cicd](pictures/nahub-cicd.png)


# How NAutoHUB Fits

- NAutoHUB supports virtual testing by running Jenkins pipeline tasks and simulating networks in Containerlab.
- It serves as a tool for lab environments, allowing test engineers to quickly configure, validate, and troubleshoot networks.
- Production Ready: NAutoHUB can be packaged and delivered to customers, acting as a single Network Source of Truth (NSOT) to manage and automate their existing network infrastructure.

<br><br>

---

# 🚀 NAutoHUB Setup Guide

This guide walks you through setting up the NAutoHUB

## 📦 Prerequisites
- Ubuntu 20.04+
- Git installed
- Internet connection (LOL)

## 🤖 Automated Setup

#### 1. Clone the repo:

 ```bash
 mkdir -p ~/projects
 cd ~/projects
 git clone https://github.com/NetEngBuff/NAutoHUB.git
 ```

#### 2. Create executables:

```bash
cd NAutoHUB/pilot-config
chmod +x requirements.sh pilot.sh
```

#### 3. `requirements.sh` installs Docker, Containerlab, InfluxDB, Grafana, Ngrok, Java, Jenkins and Python packages like snmp-mibs, easysnmp, netmiko, flask etc.

```bash
./requirements.sh
```

#### 4. `pilot.sh`,
   - creates docker images necessary
   - creates managment network interfaces and add routes for the containerlabs
   - runs an example containerlab topology
   - creates crafted services like ipam, snmp, ngrok, device health checks, etc
   - initiates the frontend

```bash
./pilot.sh
```

## 🛠️ CI/CD Implemenetation: (Optional) 

#### 1. Jenkins & Ngrok Configuration

- Get your [Ngrok auth token](https://dashboard.ngrok.com/get-started/your-authtoken) and paste it into `/NAutoHUB/misc/ngrok_config.yml`:

```yaml
version: "2"
agent:
  authtoken: <your_token>
  region: us
tunnels:
  jenkins:
    addr: 8080
    proto: http
```
- Restart the service

```bash
sudo systemctl restart ngrok.service
 ```
 
- Retrieve the initial admin password from jenkins service:

 ```bash
 sudo cat /var/lib/jenkins/secrets/initialAdminPassword
 ```

- Access the Ngrok URL from `/NAutoHUB/logs/ngrok.log`, complete Jenkins setup in browser.

#### 2. GitHub Webhook

- Push this repo to GitHub.
- Go to GitHub → **Settings > Webhooks**
- Use your Ngrok URL + `/github-webhook/`:

```text
https://<your-ngrok>.ngrok-free.app/github-webhook/
```

<br><br>

---

## ✅ Troubleshooting

- If you're running into permission errors or your WSL Ubuntu user can't run sudo, it likely means your user isn't in the sudoers group. 

Run the following in Command Prompt or PowerShell as Administrator:

```bash
  wsl -u root
  usermod -aG sudo <your_wsl_username>
```
