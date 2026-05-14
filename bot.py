#!/usr/bin/env python3
"""
APEXCRACK BOT - ULTIMATE EDITION
Wi-Fi Security Testing Telegram Bot
"""

import asyncio, subprocess, os, csv, json, time, glob, hashlib, re, threading, base64
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import requests
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TOKEN_HERE")
OWNER_ID = None
BASE_DIR = Path("/app/data")
CAPTURE_DIR = BASE_DIR / "captures"
WORDLIST_DIR = BASE_DIR / "wordlists"
REPORT_DIR = BASE_DIR / "reports"
for d in [BASE_DIR, CAPTURE_DIR, WORDLIST_DIR, REPORT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

scanned_networks = {}
cracked_passwords = {}
pending_commands = []
attack_history = []
flask_app = Flask(__name__)

def is_owner(update: Update) -> bool:
    global OWNER_ID
    if OWNER_ID is None: OWNER_ID = update.effective_user.id
    return update.effective_user.id == OWNER_ID

def get_vendor(bssid):
    oui = bssid.replace(":", "").upper()[:6]
    try:
        resp = requests.get(f"https://api.macvendors.com/{bssid}", timeout=5)
        if resp.status_code == 200: return resp.text.strip()
    except: pass
    vendor_db = {"B40F3B":"Intel","B04E26":"TP-Link","D83214":"Xiaomi","0840F3":"Tenda","500FF5":"D-Link","C83A35":"Tenda","CC2D21":"Tenda","18A6F7":"TP-Link","24A43C":"Online","D4B108":"Sardar","C40683":"Huawei","6A28F6":"YOTC","7228F6":"YOTC"}
    return vendor_db.get(oui, f"Unknown ({oui})")

def analyze_signal(rssi):
    if rssi >= -50: return "Excellent","🟢"
    elif rssi >= -60: return "Very Good","🟢"
    elif rssi >= -70: return "Good","🟡"
    elif rssi >= -80: return "Fair","🟠"
    else: return "Weak/Poor","🔴"

def generate_wordlist(ssid):
    base = ["password","12345678","admin","qwerty","letmein","123456789","monkey","dragon","master","123123","welcome","shadow","sunshine","princess","football","password123","admin123","qwerty123","letmein123"]
    clean = re.sub(r'[^a-zA-Z0-9]','',ssid).lower()
    words = set()
    for w in base:
        words.add(w); words.add(w+"123"); words.add(w+"@123"); words.add(w.capitalize()); words.add(w.upper())
    words.add(clean); words.add(clean+"123"); words.add(clean+"@123"); words.add(clean+"wifi"); words.add(clean+"2024"); words.add(clean+"2025"); words.add(clean+"2026"); words.add("admin"+clean)
    path = WORDLIST_DIR / f"custom_{clean}.txt"
    with open(path,"w") as f:
        for w in sorted(words): f.write(w+"\n")
    return str(path), len(words)

def geolocate_bssid(bssid):
    results = {}
    session = requests.Session()
    session.headers.update({'User-Agent':'ApexCrack/2.0'})
    try:
        resp = session.post("https://gs-loc.apple.com/clls/wloc",json={"wifi":[{"bssid":bssid}]},timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("locations"):
                loc = data["locations"][0]
                results["apple"] = {"lat":loc["lat"],"lon":loc["lon"],"accuracy":loc.get("accuracy")}
    except: pass
    try:
        resp = session.post("https://www.googleapis.com/geolocation/v1/geolocate",json={"wifiAccessPoints":[{"macAddress":bssid}]},timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("location"):
                results["google"] = {"lat":data["location"]["lat"],"lon":data["location"]["lng"],"accuracy":data.get("accuracy")}
    except: pass
    return results

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global OWNER_ID
    if OWNER_ID is None: OWNER_ID = update.effective_user.id
    await update.message.reply_text(
        "🦅 APEXCRACK BOT ONLINE\n\n"
        "/scan - Scan networks\n"
        "/networks - View networks\n"
        "/info name - Details\n"
        "/geo bssid - Location\n"
        "/vendor bssid - Manufacturer\n"
        "/attack name - Full attack\n"
        "/results - Cracked passwords\n"
        "/report name - Report\n"
        "/learn topic - Learn\n"
        "/status - Bot status",
        parse_mode='Markdown'
    )

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    pending_commands.append({"type":"scan","timestamp":time.time()})
    await update.message.reply_text("📡 Scan request sent to phone")

async def networks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    print(f"NETWORKS: scanned={len(scanned_networks)}")
    if not scanned_networks:
        await update.message.reply_text("No networks. Use /scan first.")
        return
    response = f"📡 {len(scanned_networks)} Networks:\n\n"
    for bssid, net in list(scanned_networks.items())[:15]:
        bars, emoji = analyze_signal(net.get('rssi',-100))
        response += f"{emoji} {net.get('ssid','Hidden')}\n  `{bssid}` | {bars} | {net.get('rssi','N/A')} dBm\n\n"
    await update.message.reply_text(response, parse_mode='Markdown')

async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    target = " ".join(context.args).strip().lower() if context.args else ""
    print(f"INFO: target='{target}' args={context.args}")
    if not target:
        await update.message.reply_text("Usage: /info [name or BSSID]")
        return
    found = None
    for bssid, net in scanned_networks.items():
        ssid_lower = net.get('ssid','').lower().strip()
        bssid_lower = bssid.lower().strip()
        if ssid_lower == target or bssid_lower == target or target in ssid_lower or target in bssid_lower:
            found = net
            break
    if not found:
        await update.message.reply_text(f"'{target}' not found. Try /networks first.")
        return
    bssid = found['bssid']
    vendor = get_vendor(bssid)
    bars, emoji = analyze_signal(found.get('rssi',-100))
    geo = geolocate_bssid(bssid)
    caps = found.get('capabilities','')
    vulns = []
    if "WPS" in caps: vulns.append("⚠️ WPS Enabled")
    if "WEP" in caps: vulns.append("🚨 WEP - Crackable in minutes")
    if not vulns: vulns.append("ℹ️ No obvious vulnerabilities")
    response = f"🎯 {found.get('ssid','Hidden')}\n\n📡 BSSID: `{bssid}`\n🏭 Vendor: {vendor}\n📶 Signal: {bars} ({found.get('rssi','N/A')} dBm)\n📡 Freq: {found.get('frequency_mhz','N/A')} MHz\n🔒 Security: {caps[:60]}\n\n⚠️ Vulns:\n" + "\n".join(vulns)
    if geo:
        response += "\n\n📍 Location:\n"
        for src, data in list(geo.items())[:2]:
            response += f"{src}: {data['lat']},{data['lon']}\nhttps://maps.google.com/?q={data['lat']},{data['lon']}\n"
    await update.message.reply_text(response, parse_mode='Markdown', disable_web_page_preview=True)

async def geo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    if not context.args:
        await update.message.reply_text("Usage: /geo [BSSID]")
        return
    bssid = context.args[0].strip()
    geo = geolocate_bssid(bssid)
    if geo:
        response = f"📍 {bssid}\n\n"
        for src, data in geo.items():
            response += f"{src}: {data['lat']},{data['lon']}\nhttps://maps.google.com/?q={data['lat']},{data['lon']}\n\n"
    else:
        response = "No location found."
    await update.message.reply_text(response, parse_mode='Markdown', disable_web_page_preview=True)

async def vendor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    if not context.args:
        await update.message.reply_text("Usage: /vendor [BSSID]")
        return
    bssid = context.args[0].strip()
    vendor = get_vendor(bssid)
    await update.message.reply_text(f"🏭 {vendor}\n`{bssid}`", parse_mode='Markdown')

async def attack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    target = " ".join(context.args).strip().lower() if context.args else ""
    if not target:
        await update.message.reply_text("Usage: /attack [name]")
        return
    found = None
    for bssid, net in scanned_networks.items():
        if net.get('ssid','').lower().strip() == target or target in net.get('ssid','').lower():
            found = net; break
    if not found:
        await update.message.reply_text(f"'{target}' not found. /networks first.")
        return
    msg = await update.message.reply_text(f"🎯 {found['ssid']}\n⏳ Phase 1: Recon...", parse_mode='Markdown')
    bssid = found['bssid']
    vendor = get_vendor(bssid)
    caps = found.get('capabilities','')
    await msg.edit_text(f"🎯 {found['ssid']}\n✅ Recon done\n📡 `{bssid}`\n🏭 {vendor}\n🔒 {caps[:50]}\n\n⏳ Phase 2: Wordlist...", parse_mode='Markdown')
    wl_path, wl_count = generate_wordlist(found['ssid'])
    cracked_passwords[found['ssid']] = {"password":"Needs handshake capture","method":"Dictionary ready","date":datetime.now().isoformat(),"bssid":bssid,"wordlist_size":wl_count}
    attack_history.append({"target":found['ssid'],"bssid":bssid,"timestamp":time.time(),"type":"attack","words":wl_count})
    await msg.edit_text(f"🎯 {found['ssid']}\n✅ Recon done\n✅ Wordlist: {wl_count} words\n🔓 Ready\n\n/results - View\n/report {found['ssid']} - Full report", parse_mode='Markdown')

async def results_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    if not cracked_passwords:
        await update.message.reply_text("No passwords cracked yet.")
        return
    response = "🔓 CRACKED:\n\n"
    for ssid, data in cracked_passwords.items():
        response += f"{ssid}: `{data['password']}`\n"
    await update.message.reply_text(response, parse_mode='Markdown')

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    target = " ".join(context.args).strip().lower() if context.args else ""
    if not target:
        await update.message.reply_text("Usage: /report [name]")
        return
    found = None
    for bssid, net in scanned_networks.items():
        if net.get('ssid','').lower().strip() == target or target in net.get('ssid','').lower():
            found = net; break
    if not found:
        await update.message.reply_text(f"'{target}' not found.")
        return
    bssid = found['bssid']
    vendor = get_vendor(bssid)
    bars, _ = analyze_signal(found.get('rssi',-100))
    cracked = cracked_passwords.get(found['ssid'],{})
    report = f"📊 REPORT: {found.get('ssid')}\n\n📡 BSSID: `{bssid}`\n🏭 {vendor}\n📶 {bars} ({found.get('rssi')} dBm)\n🔒 {found.get('capabilities','')[:60]}\n\n🔓 Password: {cracked.get('password','Not yet')}\n\n💡 Tips:\n- Use WPA3\n- Disable WPS\n- Strong password\n- Update firmware"
    await update.message.reply_text(report, parse_mode='Markdown')

async def learn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    topics = {"wpa":"WPA encrypts Wi-Fi. WPA2=AES. WPA3=SAE.","handshake":"4-way handshake proves password knowledge.","deauth":"Deauth forces reconnect to capture handshake.","wps":"WPS PIN is vulnerable. Disable it.","pmkid":"PMKID extracts key from router directly.","wep":"WEP is broken. Crackable in minutes.","wordlist":"Custom wordlists based on SSID improve cracking."}
    if not context.args:
        await update.message.reply_text("📚 /learn " + " | ".join(topics.keys()), parse_mode='Markdown')
        return
    t = context.args[0].lower()
    if t in topics: await update.message.reply_text(f"📚 {t.upper()}\n{topics[t]}", parse_mode='Markdown')
    else: await update.message.reply_text(f"Topics: {', '.join(topics.keys())}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    await update.message.reply_text(f"🦅 STATUS\n📡 Networks: {len(scanned_networks)}\n🔓 Cracked: {len(cracked_passwords)}\n🎯 Attacks: {len(attack_history)}\n🟢 Online", parse_mode='Markdown')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    await update.message.reply_text("/scan /networks /info /geo /vendor /attack /results /report /learn /status /help", parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Use the commands directly: /scan /networks /info /attack /results /status")

@flask_app.route('/api/scan-data', methods=['POST'])
def api_scan():
    data = request.json
    nets = data.get('networks',[])
    for net in nets:
        bssid = net.get('bssid','')
        if bssid:
            scanned_networks[bssid] = {**net,'last_seen':data.get('timestamp',time.time()),'scan_count':scanned_networks.get(bssid,{}).get('scan_count',0)+1}
    return jsonify({"status":"ok","received":len(nets),"total":len(scanned_networks)})

@flask_app.route('/api/pending-commands', methods=['GET'])
def api_cmds():
    global pending_commands
    cmds = pending_commands.copy()
    pending_commands = []
    return jsonify({"commands":cmds})

@flask_app.route('/api/networks', methods=['GET'])
def api_nets():
    return jsonify({"networks":list(scanned_networks.values())})

@flask_app.route('/', methods=['GET'])
def home():
    return jsonify({"bot":"APEXCRACK","status":"online","networks":len(scanned_networks)})

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT',8000)))

def main():
    print("APEXCRACK BOT STARTING")
    threading.Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.add_handler(CommandHandler("networks", networks_cmd))
    app.add_handler(CommandHandler("info", info_cmd))
    app.add_handler(CommandHandler("geo", geo_cmd))
    app.add_handler(CommandHandler("vendor", vendor_cmd))
    app.add_handler(CommandHandler("attack", attack_cmd))
    app.add_handler(CommandHandler("results", results_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CommandHandler("learn", learn_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("BOT RUNNING")
    app.run_polling()

if __name__ == "__main__":
    main()
