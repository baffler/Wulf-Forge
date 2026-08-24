# Wulf Forge: Wulfram 2 Server Emulator

## Getting Started
* Clone or download Wulf-Forge. A release-ready Wulfram II client is included in `client/`.
* Install Python (tested with Python 3.12 or newer).

### To get the server running
* From the Wulf-Forge directory, run `launch-local.cmd`.
* The launcher starts `main.py`, waits for the server port, and then runs the in-tree
  `client/wulfram2.exe` with `-root -windowed`.
* To use a separate client installation, pass `-GameDir C:\path\to\Game` to
  `launch-local.ps1`.

### Make another Wulfram 2 installation connect to the server
* You'll need to pass a couple of parameters to get it working
* You can run wulfram2.exe with command arguments `-root -windowed`
* The simpliest way to do this is to create a text file alongside the exe (wherever you installed Wulfram 2)
* Put `-root -windowed` into the text file, then save it as `launch.w2l`
* It should associate the .w2l file with Wulfram and  you can just double click to launch the game now
* Alternatively you can create a text file in the directory and put the arguments on each line:

```
-root
-windowed
```

* Save it as `_override_args` (No file extension)
* Then you can just launch the wulfram exe and it will let you connect to the local server

## Server Configuration

Wulf-Forge reads `config.toml` from the server directory.

Choose the default playable vehicle with `player.unit_type`: `0` is the tank
and `1` is the scout. A connected player can also use `/s vehicle tank` or
`/s vehicle scout`; the selection applies on the next spawn.

### Network Address

The default network config is:

```toml
[network]
host = "0.0.0.0"
server_ip = "auto"
tcp_port = 2627
udp_port = 2627
```

`host` is the address the server binds to. `server_ip` is the address advertised
back to Wulfram 2 clients for UDP traffic.

For same-machine and LAN/VPN testing, `server_ip = "auto"` is recommended. It
uses the local address of the accepted TCP connection, so a localhost client gets
localhost and a LAN/VPN client gets a reachable server address. You can set an
explicit IP if you need to force one.

### Sync Modes

Wulf-Forge has two sync modes:

```toml
[sync]
mode = "server_simulation"
```

`server_simulation` is the default. Client action packets are decoded and stored,
and server-side movement simulation can use those inputs.

`client_state_relay` is experimental. It is intended for a modified client such
as W2Mod, where the client sends local position, velocity, rotation, and angular
velocity to Wulf-Forge. The server applies that state to the player's entity and
rebroadcasts it with the normal entity update packets.

Update arrays are automatically split at a 1,200-byte encoded-packet budget and
at the protocol's 255-entity limit to avoid fragmented or truncated updates.

To enable the W2Mod relay path:

```toml
[sync]
mode = "client_state_relay"

[mod_relay]
port = 28010
owner_auth = true
debug_mapping = true
auto_bind = true
identity_trace = true
coalesce_updates = true
echo_owner_state = false
hard_sync = false
adaptive_hard_sync = true
hard_sync_teleport_distance = 250.0
hard_sync_stale_ms = 500
hard_sync_initial_packets = 3
apply_velocity = true
apply_rotation = true
apply_spin = false
```

The relay listens for fixed-size `W2MS` UDP client-state packets on
`mod_relay.port`. This is an owner-authoritative testing path, not the original
server-authoritative simulation model. Leave `mode = "server_simulation"` unless
you are running a compatible modified client.

## Loading Maps
* Before spawning in you can use `/s map <map name>`
* The server loads the bundled maps from `client/data/maps` automatically.
* A map placed in `shared/data/maps` overrides a bundled map with the same name.
* And (depending on the map) you can use `/s loadmap <map name>` to load in the `state` file from the map
* This will load the initial base setup, with repair pads and other base units
* Not all maps have state files, some have multiple

## Better Fullscreen Support (DDrawCompat)
* This will require you to remove `-windowed` from the command arguments.
* Download [DDrawCompat-v0.7.1.zip](https://github.com/narzoul/DDrawCompat/releases/download/v0.7.1/DDrawCompat-v0.7.1.zip)
* Extract ddraw.dll next to the wulfram2.exe
* You can run wulfram2 now, and login, and press Esc, go to Options->Configure Graphics
* Switch to D3D Alpha, set Visibility and Landscape Quality all the way up.
* Now close out of wulfram2
* Download [DDrawCompat-wulfram2.ini](https://github.com/baffler/Wulf-Forge/blob/b84d60d93d2bf5c6b758c146edf96117501ecf94/DDrawCompat-wulfram2.ini) and put next to the wulfram2.exe
* You can launch wulfram2.exe and fullscreen should be pretty flawless
* You can also press Shift + F11 to bring up the configuration editor in game as well for DDrawCompat.

## History
(From the Facebook group)

The best free game which refuses to die. As of October 2010, Slurpy-the Divine One-has resurrected the game once again. And sometime in 2011, the game went down again. Shit.
Wulfram 2 is(was) a multiplayer online-game involving strategy, skill, and vulching; vulching is the best. It peaked around 2001-2002, when seeing over forty-five people in each server was fairly common. Wulfram lagged and lagged to a point where players were lucky to get in a game of three on three as other prominent online games emerged(and since America legalized Absynthe). Sometime in November 2009 the website and game finally went down, effectively terminating the addictions of the last few dedicated fans. Most of the community have moved on to better things including alcohol, women, and Xbox Live. But here in this group you will find a core understanding and respect of what use to be one of the most exciting, amusing-let us not forget aggravating-online experiences to have ever existed: Wulfram II.

-Ultracrayon
