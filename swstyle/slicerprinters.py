"""Talking to the printers the way Orca Slicer and Bambu Studio do, in plain Python (no extra
packages): finding them on the network, their live status, the camera, sending a sliced file and
starting the print.

- Bambu Lab printers in LAN mode: status and commands over MQTT (TLS, port 8883, user "bblp",
  password = the printer's access code), files over FTPS (implicit TLS, port 990), the P1/A1
  camera as JPEG frames over TLS on port 6000. Found by their SSDP announcements (UDP 2021).
  A Bambu Lab account login lists the account's printers with their access codes.
- Elegoo printers (Centauri Carbon...) with Elegoo Link / SDCP: status and commands over a
  websocket (port 3030), files by HTTP upload in 1 MB parts (uploadFile/upload), the camera as
  MJPEG (port 3031). Found by a UDP broadcast "M99999" to port 3000.
- Klipper printers (Moonraker: Sovol, Creality K1, Voron...) and OctoPrint, as Orca Slicer's
  physical printer hosts: typed in by address (Orca finds them the same way), status by HTTP
  polling, files by multipart upload, the camera as the MJPEG stream the host names.

Everything here runs in worker threads; callers get plain dicts."""

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import FreeCAD as App

PARAM = "User parameter:BaseApp/Preferences/Mod/SolidWorksStyle/Slicer"
BAMBU_API = "https://api.bambulab.com"
BAMBU_MQTT_CLOUD = "us.mqtt.bambulab.com"
HTTP_KINDS = ("moonraker", "octoprint")
PRUSALINK = "prusalink"
# what each kind of printer lets the Device panel do (a control the printer has no command for is not shown)
NO_CONTROLS = {PRUSALINK: ("light", "camera", "temperature", "speed", "fans", "jog", "home", "gcode", "chamber")}


def can(kind, what):
    return what not in NO_CONTROLS.get(kind, ())


def plain_error(error, row=None):
    """A network failure in plain words: which printer, what went wrong and what to check."""
    import errno
    import ftplib
    row = row or {}
    name = row.get("name") or row.get("ip") or "The printer"
    where = row.get("ip") or "its address"
    kind = row.get("kind", "")
    if isinstance(error, urllib.error.URLError) and not isinstance(error, urllib.error.HTTPError) \
            and isinstance(error.reason, BaseException):
        error = error.reason
    check = {"bambu": "is it on, and is LAN mode on (printer screen: Settings > Network)?",
             "prusalink": "is it on, with PrusaLink on (printer screen: Settings > Network > PrusaLink)?",
             "elegoo": "is it on and on the same network?",
             "octoprint": "is OctoPrint running, and is the port right?",
             "moonraker": "is Klipper (Moonraker) running, and is the port right (usually 7125)?"}.get(
        kind, "is it on and on the same network?")
    if isinstance(error, ftplib.error_perm) and str(error).startswith("530"):
        return "%s did not take the access code for the file upload: check it on the printer screen " \
               "(Settings > Network)." % name
    if isinstance(error, ftplib.Error):
        return "%s refused the file: %s" % (name, str(error).strip())
    if isinstance(error, ConnectionRefusedError):
        return "%s did not answer at %s: %s" % (name, where, check)
    if isinstance(error, (socket.timeout, TimeoutError)):
        return "%s did not answer at %s in time: check the address, and that it is on and on this network." % (
            name, where)
    if isinstance(error, socket.gaierror):
        return "The address %s is not known on this network: check it (the printer screen shows it)." % where
    if isinstance(error, OSError) and getattr(error, "errno", None) in (errno.EHOSTUNREACH, errno.ENETUNREACH,
                                                                        errno.EHOSTDOWN):
        return "No way to %s from this computer: check the address and that both are on the same network." % where
    if isinstance(error, ssl.SSLError):
        return "The secure connection to %s failed (%s)." % (name, getattr(error, "reason", None) or error)
    if isinstance(error, ConnectionResetError):
        return "%s closed the connection: try again; if it keeps happening, restart the printer." % name
    text = str(error).strip() or error.__class__.__name__
    return text[0].upper() + text[1:] if text else text


def params():
    return App.ParamGet(PARAM)


def _insecure_context():
    """The printers use self-signed certificates (the slicers do not check them on the LAN)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ---------------------------------------------------------------------- the saved printers
def saved_printers():
    try:
        rows = json.loads(params().GetString("Printers", "[]") or "[]")
        return [r for r in rows if isinstance(r, dict) and (r.get("ip") or r.get("serial"))]
    except ValueError:
        return []


def save_printers(rows):
    params().SetString("Printers", json.dumps(rows))


def add_printer(row):
    rows = [r for r in saved_printers() if not _same_printer(r, row)]
    rows.append(row)
    save_printers(rows)
    return rows


def remove_printer(row):
    rows = [r for r in saved_printers() if not _same_printer(r, row)]
    save_printers(rows)
    return rows


def _same_printer(a, b):
    if a.get("serial") and a.get("serial") == b.get("serial"):
        return True
    return bool(a.get("ip")) and a.get("ip") == b.get("ip") and a.get("kind") == b.get("kind")


# ---------------------------------------------------------------------- discovery
def discover(seconds=4.0):
    """Printers announcing themselves on the local network: [{"kind", "name", "ip", "serial",
    "model"}]. Bambu Lab printers send SSDP NOTIFY every few seconds; Elegoo printers answer
    a broadcast."""
    found = {}

    def bambu():
        for port in (2021, 1990):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("", port))
                try:
                    mreq = struct.pack("4sl", socket.inet_aton("239.255.255.250"), socket.INADDR_ANY)
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                except OSError as _fw_err:
                    _fw_log("slicerprinters.py:112", _fw_err)
                s.settimeout(0.5)
            except OSError:
                continue
            end = time.time() + seconds
            while time.time() < end:
                try:
                    data, addr = s.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                row = parse_ssdp(data.decode("utf-8", "replace"), addr[0])
                if row:
                    found[row["serial"] or row["ip"]] = row
            s.close()
            return

    def elegoo():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.settimeout(0.5)
            s.sendto(b"M99999", ("255.255.255.255", 3000))
        except OSError:
            return
        end = time.time() + seconds
        while time.time() < end:
            try:
                data, addr = s.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break
            row = parse_elegoo_hello(data, addr[0])
            if row:
                found[row["serial"] or row["ip"]] = row
        s.close()

    threads = [threading.Thread(target=f, daemon=True) for f in (bambu, elegoo)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(seconds + 1.5)
    return sorted(found.values(), key=lambda r: (r["kind"], r["name"]))


def parse_ssdp(text, ip):
    if "bambu" not in text.lower():
        return None
    head = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            head[k.strip().lower()] = v.strip()
    return {"kind": "bambu", "name": head.get("devname.bambu.com") or head.get("usn", "Bambu Lab printer"),
            "ip": head.get("location") or ip, "serial": head.get("usn", ""),
            "model": head.get("devmodel.bambu.com", ""), "access_code": ""}


def parse_elegoo_hello(data, ip):
    try:
        msg = json.loads(data.decode("utf-8", "replace"))
    except ValueError:
        return None
    d = msg.get("Data") or msg
    attrs = d.get("Attributes") or d
    return {"kind": "elegoo", "name": attrs.get("Name") or attrs.get("MachineName") or "Elegoo printer",
            "ip": attrs.get("MainboardIP") or ip, "serial": attrs.get("MainboardID", ""),
            "model": attrs.get("MachineName", ""), "access_code": ""}


# ---------------------------------------------------------------------- a small MQTT client
class MQTT:
    """MQTT 3.1.1 over TLS, just what the printers need: connect, subscribe, publish, receive."""

    def __init__(self, host, port, username, password, on_message, client_id=None):
        self.host, self.port = host, port
        self.username, self.password = username, password
        self.on_message = on_message
        self.client_id = client_id or "swstyle-" + uuid.uuid4().hex[:12]
        self.sock = None
        self.lock = threading.Lock()
        self.alive = False
        self.packet_id = 1

    @staticmethod
    def _str(s):
        b = s.encode("utf-8")
        return struct.pack("!H", len(b)) + b

    @staticmethod
    def _len(n):
        out = b""
        while True:
            byte = n % 128
            n //= 128
            out += bytes([byte | (0x80 if n else 0)])
            if not n:
                return out

    def _send(self, kind, body):
        with self.lock:
            self.sock.sendall(bytes([kind]) + self._len(len(body)) + body)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    def _read(self):
        head = self._recv_exact(1)[0]
        mult, n = 1, 0
        while True:
            b = self._recv_exact(1)[0]
            n += (b & 127) * mult
            if not b & 128:
                break
            mult *= 128
        return head, self._recv_exact(n) if n else b""

    def connect(self, timeout=8.0):
        raw = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock = _insecure_context().wrap_socket(raw, server_hostname=self.host)
        flags = 0x02 | (0x80 if self.username else 0) | (0x40 if self.password else 0)
        body = self._str("MQTT") + bytes([4, flags]) + struct.pack("!H", 60) + self._str(self.client_id)
        if self.username:
            body += self._str(self.username)
        if self.password:
            body += self._str(self.password)
        self._send(0x10, body)
        try:
            kind, data = self._read()
        except (ssl.SSLError, ConnectionError, OSError):
            # some brokers drop the line instead of answering a bad password
            raise ConnectionError("the printer closed the connection: check the access code")
        if kind >> 4 != 2 or len(data) < 2 or data[1] != 0:
            code = data[1] if len(data) > 1 else -1
            raise ConnectionError("the printer refused the access code" if code in (4, 5) else "refused (%s)" % code)
        self.sock.settimeout(None)
        self.alive = True
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._ping, daemon=True).start()

    def subscribe(self, topic):
        self.packet_id += 1
        self._send(0x82, struct.pack("!H", self.packet_id) + self._str(topic) + b"\x00")

    def publish(self, topic, payload):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        self._send(0x30, self._str(topic) + payload)

    def _loop(self):
        try:
            while self.alive:
                kind, data = self._read()
                if kind >> 4 == 3:
                    n = struct.unpack("!H", data[:2])[0]
                    topic = data[2:2 + n].decode("utf-8", "replace")
                    rest = data[2 + n:]
                    if (kind >> 1) & 3:          # QoS 1/2 carries a packet id
                        rest = rest[2:]
                    try:
                        self.on_message(topic, rest)
                    except Exception as _fw_err:
                        _fw_log("slicerprinters.py:284", _fw_err)
        except Exception as _fw_err:
            _fw_log("slicerprinters.py:286", _fw_err)
        self.alive = False
        try:
            self.on_message(None, None)          # connection lost
        except Exception as _fw_err:
            _fw_log("slicerprinters.py:291", _fw_err)

    def _ping(self):
        while self.alive:
            time.sleep(30)
            try:
                self._send(0xC0, b"")
            except Exception:
                break

    def close(self):
        self.alive = False
        try:
            self._send(0xE0, b"")
        except Exception as _fw_err:
            _fw_log("slicerprinters.py:306", _fw_err)
        try:
            self.sock.close()
        except Exception as _fw_err:
            _fw_log("slicerprinters.py:310", _fw_err)


# ---------------------------------------------------------------------- a small websocket client
class WebSocket:
    def __init__(self, host, port, path):
        self.sock = socket.create_connection((host, port), timeout=8)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, host, port, key))
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise ConnectionError("websocket handshake failed")
            resp += chunk
        if b" 101 " not in resp.split(b"\r\n", 1)[0]:
            raise ConnectionError("websocket refused: %s" % resp.split(b"\r\n", 1)[0].decode("latin-1"))
        self.buf = resp.split(b"\r\n\r\n", 1)[1]
        self.lock = threading.Lock()

    def send(self, text):
        data = text.encode("utf-8")
        mask = os.urandom(4)
        head = bytes([0x81])
        n = len(data)
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack("!H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack("!Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        with self.lock:
            self.sock.sendall(head + mask + masked)

    def _exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self, timeout=None):
        self.sock.settimeout(timeout)
        while True:
            b0, b1 = self._exact(2)
            n = b1 & 127
            if n == 126:
                n = struct.unpack("!H", self._exact(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._exact(8))[0]
            mask = self._exact(4) if b1 & 0x80 else None
            data = self._exact(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            op = b0 & 0x0F
            if op == 8:
                raise ConnectionError("closed")
            if op == 9:                        # ping -> pong
                with self.lock:
                    self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if op in (1, 2):
                return data.decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except Exception as _fw_err:
            _fw_log("slicerprinters.py:383", _fw_err)


# ---------------------------------------------------------------------- one printer, live
OPEN = None     # the connected printers (a WeakSet, made on first use), closed when FreeCAD quits


def close_all():
    """FreeCAD is quitting: every connected printer stops polling and closes its camera and connection."""
    for p in list(OPEN or ()):
        try:
            p.close()
        except Exception as error:
            print("slicer printers: close at quit (%s)" % error)



def _digest_challenge(text):
    """The fields of a WWW-Authenticate: Digest challenge, or None."""
    import re
    if not text.lower().startswith("digest "):
        return None
    f = dict((k.lower(), v1 or v2) for k, v1, v2 in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]*))', text[7:]))
    return f if f.get("nonce") else None

class Printer:
    """A connected printer. status is a plain dict the Device panel shows:
    state, progress (0-100), remaining (s), layer, layers, nozzle, nozzle_target, bed, bed_target,
    chamber, file, light, error. on_status(status) and on_frame(jpeg bytes) are called from worker
    threads."""

    def __init__(self, row):
        self.row = dict(row)
        self.kind = row.get("kind", "bambu")
        self.status = {"state": "connecting"}
        global OPEN
        if OPEN is None:
            import weakref
            OPEN = weakref.WeakSet()
        OPEN.add(self)
        self.on_status = None
        self.on_frame = None
        self.mqtt = None
        self.ws = None
        self.camera_on = False
        self._camera_thread = None
        self.raw = {}
        self.polling = False

    # ------------------------------------------------------------------ connect
    def connect(self):
        if self.kind == PRUSALINK:
            self._connect_prusalink()
        elif self.kind == "bambu":
            self._connect_bambu()
        elif self.kind in HTTP_KINDS:
            self._connect_http()
        else:
            self._connect_elegoo()

    def close(self):
        self.camera_on = False
        self.polling = False
        self.on_status = self.on_frame = None       # a worker thread that is still running calls nobody
        if self.mqtt is not None:
            self.mqtt.close()
        if self.ws is not None:
            self.ws.close()

    def _emit(self, **changes):
        self.status.update(changes)
        if self.on_status:
            self.on_status(dict(self.status))

    # ------------------------------------------------------------------ Bambu Lab
    def _connect_bambu(self):
        row = self.row
        serial = row.get("serial", "")
        if row.get("cloud") and not row.get("ip"):
            token, uid = row.get("token", ""), row.get("uid", "")
            self.mqtt = MQTT(BAMBU_MQTT_CLOUD, 8883, "u_%s" % uid, token, self._bambu_message)
        else:
            self.mqtt = MQTT(row["ip"], 8883, "bblp", row.get("access_code", ""), self._bambu_message)
        self.mqtt.connect()
        self.mqtt.subscribe("device/%s/report" % serial)
        self.bambu_request({"pushing": {"sequence_id": "0", "command": "pushall", "version": 1, "push_target": 1}})
        self._emit(state="connected")

    def bambu_request(self, payload):
        self.mqtt.publish("device/%s/request" % self.row.get("serial", ""), payload)

    def _bambu_message(self, topic, data):
        if topic is None:
            self._emit(state="offline")
            return
        try:
            msg = json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            return
        p = msg.get("print")
        if not isinstance(p, dict):
            return
        self.raw.update(p)
        r = self.raw
        lights = {x.get("node"): x.get("mode") for x in r.get("lights_report") or [] if isinstance(x, dict)}
        state = (r.get("gcode_state") or "").lower() or "idle"
        self._emit(state=state, progress=r.get("mc_percent"), remaining=(r.get("mc_remaining_time") or 0) * 60,
                   layer=r.get("layer_num"), layers=r.get("total_layer_num"),
                   nozzle=r.get("nozzle_temper"), nozzle_target=r.get("nozzle_target_temper"),
                   bed=r.get("bed_temper"), bed_target=r.get("bed_target_temper"),
                   chamber=r.get("chamber_temper"), file=r.get("subtask_name") or r.get("gcode_file"),
                   light=lights.get("chamber_light"), speed=r.get("spd_lvl"),
                   error=r.get("print_error") or 0, ams=r.get("ams"))

    # ------------------------------------------------------------------ Elegoo (SDCP)
    def _connect_elegoo(self):
        self.ws = WebSocket(self.row["ip"], 3030, "/websocket")
        threading.Thread(target=self._elegoo_loop, daemon=True).start()
        threading.Thread(target=self._elegoo_poll, daemon=True).start()
        self._emit(state="connected")

    def elegoo_command(self, cmd, data=None):
        msg = {"Id": "", "Data": {"Cmd": cmd, "Data": data or {}, "RequestID": uuid.uuid4().hex,
                                  "MainboardID": self.row.get("serial", ""), "TimeStamp": int(time.time()),
                                  "From": 1}}
        self.ws.send(json.dumps(msg))

    def _elegoo_poll(self):
        while self.ws is not None:
            try:
                self.elegoo_command(0)
            except Exception:
                break
            time.sleep(5)

    def _elegoo_loop(self):
        try:
            while True:
                msg = json.loads(self.ws.recv())
                st = msg.get("Status") or (msg.get("Data") or {}).get("Status")
                if isinstance(st, dict):
                    self.raw.update(st)
                    self._elegoo_status()
                data = msg.get("Data") or {}
                if isinstance(data, dict) and data.get("Cmd") == 386:
                    url = (data.get("Data") or {}).get("VideoUrl")
                    if url:
                        self.row["video_url"] = url if url.startswith("http") else "http://" + url
        except Exception:
            self._emit(state="offline")

    ELEGOO_STATES = {0: "idle", 1: "printing", 2: "printing", 3: "printing", 5: "pause", 6: "pause",
                     8: "prepare", 9: "finish", 13: "printing", 14: "failed", 16: "running"}

    def _elegoo_status(self):
        r = self.raw
        info = r.get("PrintInfo") or {}
        code = info.get("Status", 0)
        cur = r.get("CurrentStatus")
        busy = (cur[0] if isinstance(cur, list) and cur else cur) or 0
        state = self.ELEGOO_STATES.get(code, "printing" if busy else "idle")
        total = info.get("TotalTicks") or 0
        now = info.get("CurrentTicks") or 0
        progress = info.get("Progress")
        if progress is None and total:
            progress = int(100 * now / total)
        temps = r.get("TempOfNozzle"), r.get("TempTargetNozzle"), r.get("TempOfHotbed"), r.get("TempTargetHotbed")
        light = (r.get("LightStatus") or {}).get("SecondLight")
        self._emit(state=state, progress=progress, remaining=max(0, (total - now)) if total else None,
                   layer=info.get("CurrentLayer"), layers=info.get("TotalLayer"),
                   nozzle=temps[0], nozzle_target=temps[1], bed=temps[2], bed_target=temps[3],
                   chamber=r.get("TempOfBox"), file=info.get("Filename"),
                   light=("on" if light else "off") if light is not None else None, error=0)

    # ------------------------------------------------------------------ Klipper (Moonraker) / OctoPrint
    def base_url(self):
        """http://host[:port]: the address as typed (a port or a full URL is kept), else the host's
        usual port (Moonraker 7125, OctoPrint 80)."""
        ip = self.row["ip"].strip().rstrip("/")
        if ip.startswith("http://") or ip.startswith("https://"):
            return ip
        if ":" in ip or self.kind in ("octoprint", PRUSALINK):
            return "http://" + ip
        return "http://%s:%d" % (ip, int(self.row.get("port") or 7125))

    def http(self, method, path, body=None, headers=None, timeout=10):
        h = {"Accept": "application/json"}
        if self.row.get("access_code"):
            # OctoPrint's API key; Moonraker takes one too when its API key login is on
            h["X-Api-Key"] = self.row["access_code"]
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        req = urllib.request.Request(self.base_url() + path, data=body, method=method, headers=h)
        data = urllib.request.urlopen(req, timeout=timeout).read()
        try:
            return json.loads(data.decode("utf-8", "replace")) if data else {}
        except ValueError:
            return {}

    def _connect_http(self):
        if self.kind == "moonraker":
            info = self.http("GET", "/server/info").get("result") or {}
            self.raw["klippy"] = info.get("klippy_state")
        else:
            self.http("GET", "/api/version")
        self.polling = True
        threading.Thread(target=self._http_poll, daemon=True).start()
        self._emit(state="connected")

    def _http_poll(self):
        while self.polling:
            try:
                (self._moonraker_status if self.kind == "moonraker" else self._octoprint_status)()
            except Exception as error:
                self._emit(state="offline", error=str(error))
            time.sleep(2)

    MOONRAKER_STATES = {"standby": "idle", "printing": "printing", "paused": "pause", "complete": "finish",
                        "cancelled": "failed", "error": "failed"}

    def _moonraker_status(self):
        q = "/printer/objects/query?print_stats&display_status&virtual_sdcard&extruder&heater_bed"
        st = (self.http("GET", q).get("result") or {}).get("status") or {}
        ps, ds = st.get("print_stats") or {}, st.get("display_status") or {}
        ex, bed = st.get("extruder") or {}, st.get("heater_bed") or {}
        progress = ds.get("progress", (st.get("virtual_sdcard") or {}).get("progress"))
        done = ps.get("print_duration") or 0
        remaining = done / progress - done if progress and progress > 0.01 else None
        info = ps.get("info") or {}
        self._emit(state=self.MOONRAKER_STATES.get(ps.get("state"), ps.get("state") or "idle"),
                   progress=int(100 * progress) if progress is not None else None, remaining=remaining,
                   layer=info.get("current_layer"), layers=info.get("total_layer"),
                   nozzle=ex.get("temperature"), nozzle_target=ex.get("target"),
                   bed=bed.get("temperature"), bed_target=bed.get("target"), file=ps.get("filename"), error=0)

    OCTOPRINT_STATES = {"Operational": "idle", "Printing": "printing", "Paused": "pause", "Pausing": "pause",
                        "Cancelling": "failed", "Offline": "offline", "Error": "failed"}

    def _octoprint_status(self):
        job = self.http("GET", "/api/job")
        try:
            temps = self.http("GET", "/api/printer?exclude=sd,state").get("temperature") or {}
        except urllib.error.HTTPError:
            temps = {}          # 409: the printer is not connected to OctoPrint
        prog = job.get("progress") or {}
        t0, bed = temps.get("tool0") or {}, temps.get("bed") or {}
        self._emit(state=self.OCTOPRINT_STATES.get(job.get("state"), "idle"),
                   progress=int(prog["completion"]) if prog.get("completion") is not None else None,
                   remaining=prog.get("printTimeLeft"), nozzle=t0.get("actual"), nozzle_target=t0.get("target"),
                   bed=bed.get("actual"), bed_target=bed.get("target"),
                   file=((job.get("job") or {}).get("file") or {}).get("name"), error=0)

    def _http_command(self, action):
        if self.kind == "moonraker":
            self.http("POST", "/printer/print/" + {"stop": "cancel"}.get(action, action))
        elif action == "stop":
            self.http("POST", "/api/job", {"command": "cancel"})
        else:
            self.http("POST", "/api/job", {"command": "pause", "action": action})

    def _http_gcode(self, line):
        if self.kind == "moonraker":
            self.http("POST", "/printer/gcode/script?script=" + urllib.parse.quote(line.strip()), timeout=30)
        else:
            self.http("POST", "/api/printer/command", {"commands": [line.strip()]})

    def _http_camera_url(self):
        if self.kind == "moonraker":
            try:
                cams = (self.http("GET", "/server/webcams/list").get("result") or {}).get("webcams") or []
                url = next((c.get("stream_url") for c in cams if c.get("enabled", True) and c.get("stream_url")), None)
            except Exception:
                url = None
            host = "http://" + urllib.parse.urlsplit(self.base_url()).hostname
            if url:
                return url if url.startswith("http") else host + "/" + url.lstrip("/")
            return host + "/webcam/?action=stream"
        try:
            url = ((self.http("GET", "/api/settings").get("webcam") or {}).get("streamUrl"))
        except Exception:
            url = None
        if url:
            return url if url.startswith("http") else self.base_url() + "/" + url.lstrip("/")
        return self.base_url() + "/webcam/?action=stream"

    def _send_http(self, path, start, options, progress):
        name = os.path.basename(path)
        content = open(path, "rb").read()
        if self.kind == "moonraker":
            fields, route = {"root": "gcodes", "print": "true" if start else "false"}, "/server/files/upload"
        else:
            fields = {"select": "true" if start else "false", "print": "true" if start else "false"}
            route = "/api/files/local"
        body, ctype = _multipart(fields, "file", name, content)
        if progress:
            progress(0, len(content))
        self.http("POST", route, body, {"Content-Type": ctype}, timeout=300)
        if progress:
            progress(len(content), len(content))
        return True

    # ------------------------------------------------------------------ PrusaLink (Prusa MK4/MK4S, XL, MINI+, CORE One)
    PRUSALINK_STATES = {"IDLE": "idle", "READY": "idle", "BUSY": "prepare", "PRINTING": "printing", "PAUSED": "pause",
                        "FINISHED": "finish", "STOPPED": "failed", "ERROR": "failed", "ATTENTION": "pause"}

    def prusalink(self, method, path, body=None, headers=None, timeout=10):
        """One PrusaLink API call: HTTP Digest login with the printer's PrusaLink user and password (printer screen:
        Settings > Network > PrusaLink), or an API key (PrusaLink on a Raspberry Pi) when no user is given.
        Returns (HTTP status, JSON answer or {})."""
        url = self.base_url() + path
        h = {"Accept": "application/json"}
        h.update(headers or {})
        user, secret = (self.row.get("user") or "").strip(), self.row.get("access_code") or ""
        if not user and secret:
            h["X-Api-Key"] = secret
        # Digest login with the printer's last challenge sent up front, so a file goes over the network once (a
        # plain Digest client sends the body, takes the 401 and sends it again)
        for attempt in (0, 1):
            hh = dict(h)
            if user and getattr(self, "_pl_digest", None):
                hh["Authorization"] = self._digest_header(method, path, user, secret)
            req = urllib.request.Request(url, data=body, method=method, headers=hh)
            try:
                resp = urllib.request.urlopen(req, timeout=timeout)
                break
            except urllib.error.HTTPError as error:
                if error.code == 401 and user and attempt == 0:
                    chal = _digest_challenge(error.headers.get("WWW-Authenticate", ""))
                    fresh = chal and (chal.get("nonce") != (getattr(self, "_pl_digest", None) or {}).get("nonce")
                                      or "Authorization" not in hh)
                    if fresh:
                        self._pl_digest, self._pl_nc = chal, 0
                        continue
                if error.code == 401:
                    raise IOError("PrusaLink did not take the user name and password (printer screen: Settings > "
                                  "Network > PrusaLink)") from None
                if error.code in (404, 409) and method == "GET":
                    return error.code, {}
                raise IOError("PrusaLink answered %d %s" % (error.code, error.reason)) from None
        data = resp.read()
        try:
            return resp.status, (json.loads(data.decode("utf-8", "replace")) if data else {})
        except ValueError:
            return resp.status, {}

    def _digest_header(self, method, path, user, secret):
        c = self._pl_digest
        self._pl_nc = getattr(self, "_pl_nc", 0) + 1
        nc, cnonce = "%08x" % self._pl_nc, uuid.uuid4().hex[:16]
        md5 = lambda t: hashlib.md5(t.encode("utf-8")).hexdigest()
        ha1, ha2 = md5("%s:%s:%s" % (user, c.get("realm", ""), secret)), md5("%s:%s" % (method, path))
        qop = "auth" if "auth" in [q.strip() for q in c.get("qop", "").split(",")] else ""
        if qop:
            resp = md5(":".join((ha1, c["nonce"], nc, cnonce, qop, ha2)))
        else:
            resp = md5("%s:%s:%s" % (ha1, c["nonce"], ha2))
        out = 'Digest username="%s", realm="%s", nonce="%s", uri="%s", response="%s"' % (
            user, c.get("realm", ""), c["nonce"], path, resp)
        if qop:
            out += ', qop=%s, nc=%s, cnonce="%s"' % (qop, nc, cnonce)
        if c.get("opaque"):
            out += ', opaque="%s"' % c["opaque"]
        return out

    def _connect_prusalink(self):
        code, info = self.prusalink("GET", "/api/v1/info")
        if code != 200:
            code, info = self.prusalink("GET", "/api/version")
        self.raw["info"] = info
        self._prusalink_status()
        self.polling = True
        threading.Thread(target=self._prusalink_poll, daemon=True).start()
        self._emit(state=self.status.get("state") or "connected")

    def _prusalink_poll(self):
        while self.polling:
            time.sleep(2)
            try:
                self._prusalink_status()
            except Exception as error:
                self._emit(state="offline", error=0, message=str(error))

    def _prusalink_status(self):
        _code, st = self.prusalink("GET", "/api/v1/status")
        pr, job = st.get("printer") or {}, st.get("job") or {}
        jid = job.get("id")
        self.raw["job_id"] = jid
        if jid is not None and self.raw.get("file_of") != jid:
            _c, j = self.prusalink("GET", "/api/v1/job")
            f = j.get("file") or {}
            self.raw["file_of"], self.raw["file"] = jid, f.get("display_name") or f.get("name")
        progress = job.get("progress")
        self._emit(state=self.PRUSALINK_STATES.get(str(pr.get("state") or "").upper(), "idle"),
                   progress=int(progress) if progress is not None else None, remaining=job.get("time_remaining"),
                   nozzle=pr.get("temp_nozzle"), nozzle_target=pr.get("target_nozzle"),
                   bed=pr.get("temp_bed"), bed_target=pr.get("target_bed"),
                   file=self.raw.get("file") if jid is not None else None, error=0)

    def _prusalink_job(self, action):
        jid = self.raw.get("job_id")
        if jid is None:
            self._prusalink_status()
            jid = self.raw.get("job_id")
        if jid is None:
            raise IOError("the printer has no print job")
        if action == "stop":
            self.prusalink("DELETE", "/api/v1/job/%s" % jid)
        else:
            self.prusalink("PUT", "/api/v1/job/%s/%s" % (jid, action))

    def _send_prusalink(self, path, start, options, progress):
        """PUT the file to the printer's storage (its USB drive, else its internal storage), started with
        Print-After-Upload (as PrusaSlicer's own PrusaLink upload)."""
        name = os.path.basename(path)
        _c, st = self.prusalink("GET", "/api/v1/storage")
        rows = [r for r in (st.get("storage_list") or []) if r.get("available", True) and not r.get("read_only")]
        storage = (rows[0].get("path") if rows else "/usb").strip("/") or "usb"
        data = open(path, "rb").read()
        if progress:
            progress(0, len(data))
        self.prusalink("PUT", "/api/v1/files/%s/%s" % (urllib.parse.quote(storage), urllib.parse.quote(name)), data,
                       {"Content-Type": "application/octet-stream", "Print-After-Upload": "?1" if start else "?0",
                        "Overwrite": "?1"}, timeout=600)
        if progress:
            progress(len(data), len(data))
        return True

    def _unsupported(self, what):
        raise NotImplementedError("PrusaLink has no command for the %s" % what)

    # ------------------------------------------------------------------ controls
    def pause(self):
        if self.kind == PRUSALINK:
            return self._prusalink_job("pause")
        if self.kind in HTTP_KINDS:
            self._http_command("pause")
        elif self.kind == "bambu":
            self.bambu_request({"print": {"sequence_id": "0", "command": "pause"}})
        else:
            self.elegoo_command(129)

    def resume(self):
        if self.kind == PRUSALINK:
            return self._prusalink_job("resume")
        if self.kind in HTTP_KINDS:
            self._http_command("resume")
        elif self.kind == "bambu":
            self.bambu_request({"print": {"sequence_id": "0", "command": "resume"}})
        else:
            self.elegoo_command(131)

    def stop(self):
        if self.kind == PRUSALINK:
            return self._prusalink_job("stop")
        if self.kind in HTTP_KINDS:
            self._http_command("stop")
        elif self.kind == "bambu":
            self.bambu_request({"print": {"sequence_id": "0", "command": "stop"}})
        else:
            self.elegoo_command(130)

    def light(self, on):
        if self.kind == PRUSALINK:
            self._unsupported("light")
        if self.kind in HTTP_KINDS:
            raise NotImplementedError("this printer's light is not named by its host")
        if self.kind == "bambu":
            self.bambu_request({"system": {"sequence_id": "0", "command": "ledctrl", "led_node": "chamber_light",
                                           "led_mode": "on" if on else "off", "led_on_time": 500,
                                           "led_off_time": 500, "loop_times": 0, "interval_time": 0}})
        else:
            self.elegoo_command(403, {"LightStatus": {"SecondLight": bool(on), "RgbLight": [0, 0, 0]}})

    def set_temperature(self, which, value):
        if self.kind == PRUSALINK:
            self._unsupported("temperatures")
        if self.kind in HTTP_KINDS:
            self._http_gcode({"nozzle": "M104 S%d", "bed": "M140 S%d"}[which] % int(value))
        elif self.kind == "bambu":
            code = {"nozzle": "M104 S%d", "bed": "M140 S%d"}[which] % int(value)
            self.bambu_request({"print": {"sequence_id": "0", "command": "gcode_line", "param": code + "\n"}})
        else:
            key = {"nozzle": "TempTargetNozzle", "bed": "TempTargetHotbed"}[which]
            self.elegoo_command(403, {key: int(value)})

    def set_speed(self, percent):
        """Print speed as the slicers' Silent 50 / Standard 100 / Sport 124 / Ludicrous 166 percent."""
        percent = int(percent)
        if self.kind == PRUSALINK:
            self._unsupported("print speed")
        if self.kind in HTTP_KINDS:
            self._http_gcode("M220 S%d" % percent)
        elif self.kind == "bambu":
            level = {50: "1", 100: "2", 124: "3", 166: "4"}.get(percent, "2")
            self.bambu_request({"print": {"sequence_id": "0", "command": "print_speed", "param": level}})
        else:
            self.elegoo_command(403, {"PrintSpeedPct": percent})

    FANS = {"part": ("M106 S%d", "ModelFan"), "aux": ("M106 P2 S%d", "AuxiliaryFan"),
            "chamber": ("M106 P3 S%d", "BoxFan")}

    def set_fan(self, which, percent):
        code, key = self.FANS[which]
        percent = max(0, min(100, int(percent)))
        if self.kind == PRUSALINK:
            self._unsupported("fans")
        if self.kind in HTTP_KINDS or self.kind == "bambu":
            self.gcode(code % round(percent * 255 / 100.0))
        else:
            self.elegoo_command(403, {"TargetFanSpeed": {key: percent}})

    def jog(self, axis, mm, feed=3000):
        """Move one axis by mm from where it is (relative move, then back to absolute)."""
        lines = ["G91", "G1 %s%g F%d" % (axis.upper(), float(mm), feed), "G90"]
        if self.kind == PRUSALINK:
            self._unsupported("moves")
        if self.kind in HTTP_KINDS:
            for line in lines:
                self._http_gcode(line)
        elif self.kind == "bambu":
            self.bambu_request({"print": {"sequence_id": "0", "command": "gcode_line", "param": "\n".join(lines) + "\n"}})
        else:
            raise NotImplementedError("Elegoo printers take no jog moves over Elegoo Link")

    def home(self):
        self.gcode("G28")

    def gcode(self, line):
        if self.kind == PRUSALINK:
            self._unsupported("G-code lines")
        if self.kind in HTTP_KINDS:
            self._http_gcode(line)
        elif self.kind == "bambu":
            self.bambu_request({"print": {"sequence_id": "0", "command": "gcode_line", "param": line.rstrip() + "\n"}})
        else:
            raise NotImplementedError("Elegoo printers take no single G-code lines over Elegoo Link")

    # ------------------------------------------------------------------ camera
    def start_camera(self):
        if self.camera_on:
            return
        if self.kind == PRUSALINK:
            self._unsupported("camera")
        self.camera_on = True
        target = self._bambu_camera if self.kind == "bambu" else self._mjpeg_camera
        self._camera_thread = threading.Thread(target=target, daemon=True)
        self._camera_thread.start()

    def stop_camera(self):
        self.camera_on = False

    def _bambu_camera(self):
        """P1 / A1 series: TLS on port 6000, an 80-byte login, then JPEG frames with a 16-byte
        header. (The X1 series streams RTSP on port 322 instead.)"""
        row = self.row
        while self.camera_on:
            try:
                raw = socket.create_connection((row["ip"], 6000), timeout=8)
                s = _insecure_context().wrap_socket(raw, server_hostname=row["ip"])
                auth = struct.pack("<IIII", 0x40, 0x3000, 0, 0)
                auth += b"bblp".ljust(32, b"\x00") + row.get("access_code", "").encode().ljust(32, b"\x00")
                s.sendall(auth)
                s.settimeout(10)
                buf = b""
                while self.camera_on:
                    while len(buf) < 16:
                        chunk = s.recv(65536)
                        if not chunk:
                            raise ConnectionError("camera closed")
                        buf += chunk
                    size = struct.unpack("<I", buf[:4])[0]
                    while len(buf) < 16 + size:
                        chunk = s.recv(65536)
                        if not chunk:
                            raise ConnectionError("camera closed")
                        buf += chunk
                    frame, buf = buf[16:16 + size], buf[16 + size:]
                    if frame[:2] == b"\xff\xd8" and self.on_frame:
                        self.on_frame(frame)
                s.close()
            except Exception as error:
                self._emit(camera_error=str(error))
                time.sleep(3)

    def _mjpeg_camera(self):
        """Elegoo: an MJPEG stream (http://<ip>:3031/video unless the printer names another)."""
        if self.kind == "elegoo":
            try:
                self.elegoo_command(386, {"Enable": 1})
                time.sleep(1.0)
            except Exception as _fw_err:
                _fw_log("slicerprinters.py:798", _fw_err)
        if self.kind in HTTP_KINDS:
            url = self._http_camera_url()
        else:
            url = self.row.get("video_url") or "http://%s:3031/video" % self.row["ip"]
        while self.camera_on:
            try:
                resp = urllib.request.urlopen(url, timeout=10)
                buf = b""
                while self.camera_on:
                    chunk = resp.read1(32768) if hasattr(resp, "read1") else resp.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while True:
                        a = buf.find(b"\xff\xd8")
                        b = buf.find(b"\xff\xd9", a + 2) if a >= 0 else -1
                        if a < 0 or b < 0:
                            break
                        frame, buf = buf[a:b + 2], buf[b + 2:]
                        if self.on_frame:
                            self.on_frame(frame)
                    if len(buf) > 4 * 1024 * 1024:
                        buf = b""
                resp.close()
            except Exception as error:
                self._emit(camera_error=str(error))
                time.sleep(3)

    # ------------------------------------------------------------------ send a print
    def send(self, path, start=True, options=None, progress=None):
        """Upload a sliced file and (start=True) start printing it. Bambu Lab printers take the
        sliced .gcode.3mf, Elegoo printers the .gcode. Raises on failure."""
        options = options or {}
        if self.kind == PRUSALINK:
            return self._send_prusalink(path, start, options, progress)
        if self.kind in HTTP_KINDS:
            return self._send_http(path, start, options, progress)
        if self.kind == "bambu":
            return self._send_bambu(path, start, options, progress)
        return self._send_elegoo(path, start, options, progress)

    def _send_bambu(self, path, start, options, progress):
        name = os.path.basename(path)
        ftp_upload(self.row["ip"], self.row.get("access_code", ""), path, name, progress)
        if not start:
            return True
        md5 = hashlib.md5(open(path, "rb").read()).hexdigest()
        self.bambu_request({"print": {
            "sequence_id": "0", "command": "project_file", "param": "Metadata/plate_%d.gcode" % options.get("plate", 1),
            "project_id": "0", "profile_id": "0", "task_id": "0", "subtask_id": "0",
            "subtask_name": name.replace(".gcode.3mf", ""), "file": name, "url": "ftp:///%s" % name, "md5": md5,
            "timelapse": bool(options.get("timelapse", False)), "bed_type": options.get("bed_type", "auto"),
            "bed_levelling": bool(options.get("bed_levelling", True)), "flow_cali": bool(options.get("flow_cali", False)),
            "vibration_cali": bool(options.get("vibration_cali", True)), "layer_inspect": bool(options.get("layer_inspect", False)),
            "use_ams": bool(options.get("use_ams", False)), "ams_mapping": options.get("ams_mapping", [])}})
        return True

    def _send_elegoo(self, path, start, options, progress):
        name = os.path.basename(path)
        elegoo_upload(self.row["ip"], path, name, progress)
        if not start:
            return True
        self.elegoo_command(128, {"Filename": "/local/" + name, "StartLayer": 0,
                                  "Calibration_switch": int(bool(options.get("bed_levelling", False))),
                                  "PrintPlatformType": int(options.get("platform", 0)),
                                  "Tlp_Switch": int(bool(options.get("timelapse", False)))})
        return True


# ---------------------------------------------------------------------- file transfer
def ftp_upload(host, access_code, path, name, progress=None, port=990):
    """Bambu Lab printers: FTPS with implicit TLS; the data channel must reuse the TLS session."""
    import ftplib

    class ImplicitFTPS(ftplib.FTP_TLS):
        def connect(self, host="", port=0, timeout=-999, source_address=None):
            self.host, self.port = host, port
            self.sock = socket.create_connection((host, port), 15)
            self.af = self.sock.family
            self.sock = self.context.wrap_socket(self.sock, server_hostname=host)
            self.file = self.sock.makefile("r", encoding=self.encoding)
            self.welcome = self.getresp()
            return self.welcome

        def ntransfercmd(self, cmd, rest=None):
            conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
            if self._prot_p:
                conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
            return conn, size

    ftp = ImplicitFTPS(context=_insecure_context())
    ftp.connect(host, port)
    ftp.login("bblp", access_code)
    ftp.prot_p()
    total = os.path.getsize(path)
    sent = [0]

    def cb(block):
        sent[0] += len(block)
        if progress:
            progress(sent[0], total)

    with open(path, "rb") as f:
        ftp.storbinary("STOR /%s" % name, f, blocksize=65536, callback=cb)
    try:
        ftp.quit()
    except Exception as _fw_err:
        _fw_log("slicerprinters.py:904", _fw_err)
    return True


def elegoo_upload(host, path, name, progress=None, part=1048576):
    """Elegoo Link: POST uploadFile/upload, multipart, 1 MB parts with the file's MD5 and an id."""
    data = open(path, "rb").read()
    md5 = hashlib.md5(data).hexdigest()
    uid = str(uuid.uuid4())
    total = len(data)
    last_error = None
    for base in ("http://%s:3030" % host, "http://%s" % host):
        try:
            for offset in range(0, max(total, 1), part):
                chunk = data[offset:offset + part]
                fields = {"Check": "1", "S-File-MD5": md5, "Offset": str(offset), "Uuid": uid, "TotalSize": str(total)}
                body, ctype = _multipart(fields, "File", name, chunk)
                req = urllib.request.Request(base + "/uploadFile/upload", data=body, method="POST",
                                             headers={"Content-Type": ctype, "Accept": "application/json"})
                resp = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace"))
                if str(resp.get("code")) != "000000":
                    raise IOError("printer refused the file: %s" % resp.get("messages") or resp)
                if progress:
                    progress(min(total, offset + len(chunk)), total)
            return True
        except (urllib.error.URLError, ConnectionError, socket.timeout) as error:
            last_error = error
            continue
    raise IOError("could not reach the printer: %s" % last_error)


def _multipart(fields, file_field, filename, content):
    boundary = "----swstyle" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode())
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                  "Content-Type: application/octet-stream\r\n\r\n" % (boundary, file_field, filename)).encode())
    parts.append(content + b"\r\n")
    parts.append(("--%s--\r\n" % boundary).encode())
    return b"".join(parts), "multipart/form-data; boundary=%s" % boundary


# ---------------------------------------------------------------------- Bambu Lab account
class BambuAccount:
    """Bambu Lab cloud login: lists the account's printers with their access codes (their LAN
    password), which is what Add Printer needs. Login may ask for an emailed code or a 2FA code."""

    def __init__(self, api=BAMBU_API):
        self.api = api
        self.token = params().GetString("BambuToken", "")
        self.uid = params().GetString("BambuUid", "")
        self.account = params().GetString("BambuAccount", "")

    def _call(self, method, path, body=None, auth=True):
        req = urllib.request.Request(self.api + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "Accept": "application/json",
                                              "User-Agent": "bambu_network_agent/01.09.05.01"})
        if auth and self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            return json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace") or "{}")
        except urllib.error.HTTPError as error:
            try:
                return json.loads(error.read().decode("utf-8", "replace"))
            except Exception:
                return {"error": "HTTP %d" % error.code}

    def login(self, account, password=None, code=None, tfa_key=None):
        """-> "ok" | "need_code" (a code was emailed) | "need_tfa" | an error message."""
        self.account = account
        if tfa_key and code:
            r = self._call("POST", "/v1/user-service/user/tfa", {"tfaKey": tfa_key, "tfaCode": code}, auth=False)
        elif code:
            r = self._call("POST", "/v1/user-service/user/login", {"account": account, "code": code}, auth=False)
        else:
            r = self._call("POST", "/v1/user-service/user/login", {"account": account, "password": password}, auth=False)
        if r.get("accessToken"):
            self.token = r["accessToken"]
            self._save()
            self._fetch_uid()
            return "ok"
        if r.get("loginType") == "verifyCode":
            self._call("POST", "/v1/user-service/user/sendemail/code", {"email": account, "type": "codeLogin"}, auth=False)
            return "need_code"
        if r.get("loginType") == "tfa":
            self.tfa_key = r.get("tfaKey", "")
            return "need_tfa"
        return r.get("message") or r.get("error") or "login failed"

    def send_code(self, account):
        """Log in without a password, as Bambu Lab offers for every account (also ones made with
        Google, Apple or Facebook): Bambu Lab emails a code to the account's address.
        -> "need_code" | an error message."""
        self.account = account
        r = self._call("POST", "/v1/user-service/user/sendemail/code", {"email": account, "type": "codeLogin"},
                       auth=False)
        if r.get("success") is False or r.get("error"):
            return r.get("message") or r.get("error") or "Bambu Lab could not send a code"
        return "need_code"

    def _fetch_uid(self):
        r = self._call("GET", "/v1/design-user-service/my/preference")
        if r.get("uid"):
            self.uid = str(r["uid"])
            self._save()

    def _save(self):
        p = params()
        p.SetString("BambuToken", self.token)
        p.SetString("BambuUid", self.uid)
        p.SetString("BambuAccount", self.account)

    def logout(self):
        self.token = self.uid = ""
        self._save()

    def logged_in(self):
        return bool(self.token)

    def printers(self):
        r = self._call("GET", "/v1/iot-service/api/user/bind")
        out = []
        for d in r.get("devices") or []:
            out.append({"kind": "bambu", "name": d.get("name") or d.get("dev_id"), "serial": d.get("dev_id", ""),
                        "model": d.get("dev_product_name") or d.get("dev_model_name", ""),
                        "access_code": d.get("dev_access_code", ""), "online": d.get("online"),
                        "ip": "", "cloud": True})
        return out


def sync_account(seconds=5.0):
    """After a Bambu Lab login, as Bambu Studio's device list: the account's printers become your
    printers, with their access codes and the addresses the network search finds for them (one
    found later fills in by its serial number). Returns the account's rows."""
    rows = BambuAccount().printers()
    try:
        found = {r.get("serial"): r for r in discover(seconds) if r.get("serial")}
    except Exception:
        found = {}
    saved = {r.get("serial"): r for r in saved_printers() if r.get("serial")}
    for r in rows:
        row = {"kind": "bambu", "name": r.get("name") or r.get("serial"), "serial": r.get("serial", ""),
               "access_code": r.get("access_code", ""), "model": r.get("model", ""),
               "ip": (found.get(r.get("serial")) or {}).get("ip") or (saved.get(r.get("serial")) or {}).get("ip", ""),
               "account": True}
        add_printer(row)
    return rows
