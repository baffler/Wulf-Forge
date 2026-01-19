import struct

class PacketLogger:
    def __init__(self):
        # Map IDs to Readable Names
        self.packet_names = {
            0x02: "D_ACK",
            0x03: "D_HANDSHAKE",
            0x08: "HELLO_ACK",
            0x09: "ACTION_DUMP",
            0x0A: "ACTION_UPDATE",
            0x0B: "PING_REQUEST",
            0x13: "SESSION_KEY",
            0x1F: "COMM_MESSAGE",
            0x20: "COMM_REQ",
            0x21: "LOGIN_REQ",
            0x24: "BEHAVIOR",
            0x33: "ACK2",
            0x40: "KEEP_ALIVE",
            0x4C: "ROUTING_PING",
            0x4D: "ID_UDP",
            0x4E: "BPS_REQUEST"
        }

    def log(self, direction, pkt_type, payload, addr=None, show_ascii=True):
        """
        Pretty prints the packet.
        direction: "RECV" or "SEND"
        """
        # --- SPAM FILTER ---
        # Comment these out if you want to see everything
        #if pkt_type in [0x0A, 0x40]: 
            #return

        name = self.packet_names.get(pkt_type, "UNKNOWN")
        hex_str = payload.hex().upper()
        length = len(payload)
        
        addr_str = f" | Addr={addr}" if addr else ""

        print(f"[{direction}] {name:<14} (0x{pkt_type:02X}) | Len={length:<3}{addr_str}")
        print(f"       Body={hex_str}") # Uncomment for full hex dump

        if show_ascii and length > 0:
            ascii_str = ""
            for byte in payload:
                if 32 <= byte <= 126:
                    ascii_str += chr(byte)
                else:
                    ascii_str += "."
            print(f"       Ascii='{ascii_str}'")
        
        print("-" * 50)