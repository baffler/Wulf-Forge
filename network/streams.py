import struct
import math

class PacketWriter:
    """
    A unified BitStream writer. 
    Everything flows through write_bits to ensure alignment is always handled automatically.
    """
    def __init__(self):
        self._buffer = bytearray()
        self._current_byte = 0
        self._bit_index = 0  # 0 to 7

    def _flush_bits(self):
        """Internal: moves the current byte into the buffer if we have pending bits."""
        if self._bit_index > 0:
            self._buffer.append(self._current_byte)
            self._current_byte = 0
            self._bit_index = 0

    def get_bytes(self) -> bytes:
        """Finalizes the stream (pads the last byte with 0s if needed) and returns the payload."""
        self._flush_bits()
        return bytes(self._buffer)

    # ------------------------------------------------------------------
    # CORE BIT LOGIC
    # ------------------------------------------------------------------
    
    def write_bytes(self, data: bytes):
        """
        Writes a raw sequence of bytes.
        Safe to call even if the stream is currently unaligned (mid-byte).
        """
        for b in data:
            self.write_byte(b)

    def write_bits(self, value: int, num_bits: int):
        """
        Writes 'num_bits' from 'value' into the stream.
        Writes from MSB to LSB (Big Endian bit order).
        """
        # Iterate from the most significant bit down to 0
        for i in range(num_bits - 1, -1, -1):
            bit = (value >> i) & 1
            
            # Place bit in the current byte at the correct position (7 down to 0)
            self._current_byte |= bit << (7 - self._bit_index)
            self._bit_index += 1

            # If byte is full, push to buffer and reset
            if self._bit_index == 8:
                self._buffer.append(self._current_byte)
                self._current_byte = 0
                self._bit_index = 0

    def align(self):
        """Forces the stream to jump to the next byte boundary."""
        if self._bit_index > 0:
            self._buffer.append(self._current_byte)
            self._current_byte = 0
            self._bit_index = 0

    # ------------------------------------------------------------------
    # STANDARD TYPES (Mapped to Bits)
    # ------------------------------------------------------------------

    def write_bool(self, value: bool):
        """Writes 1 bit."""
        self.write_bits(1 if value else 0, 1)

    def write_byte(self, value: int):
        """Writes 8 bits (unsigned)."""
        self.write_bits(value, 8)

    def write_int16(self, value: int):
        """Writes 16 bits (Big Endian)."""
        # Handle negative numbers by masking to 16 bits
        self.write_bits(value & 0xFFFF, 16)

    def write_int32(self, value: int):
        """Writes 32 bits (Big Endian)."""
        # Handle negative numbers by masking to 32 bits
        self.write_bits(value & 0xFFFFFFFF, 32)

    # ------------------------------------------------------------------
    # WULFRAM SPECIFIC TYPES
    # ------------------------------------------------------------------

    def write_float(self, value: float):
        """
        Writes a standard IEEE 754 float (32-bit).
        Used for generic floating point data.
        """
        # Pack as float, unpack as int to get the bits
        packed = struct.pack(">f", value)
        int_val = struct.unpack(">I", packed)[0]
        self.write_bits(int_val, 32)

    def write_fixed1616(self, value: float):
        """
        Writes a 16.16 Fixed Point number (32 bits total).
        Used for Positions and Velocities.
        """
        raw = int(round(value * 65536.0))
        # Mask to 32 bits to handle 2's complement negatives correctly
        self.write_bits(raw & 0xFFFFFFFF, 32)

    def write_string(self, text: str):
        """
        Writes a Pascal String: [UInt16 Length] + [ASCII Bytes] + [Null Terminator]
        Note: Based on your previous code, Wulfram strings seem to include a null terminator 
        counted in the length.
        """
        if text is None:
            text = ""
        
        # Encode to ASCII, defaulting to ? for bad chars
        raw_data = text.encode('ascii', errors='replace') + b'\x00'
        
        length = len(raw_data)
        
        # 1. Write Length (16-bit Big Endian)
        self.write_int16(length)
        
        # 2. Write Characters
        for byte_val in raw_data:
            self.write_byte(byte_val)

    def write_vector3(self, x: float, y: float, z: float):
        """Helper to write 3 fixed-point numbers."""
        self.write_fixed1616(x)
        self.write_fixed1616(y)
        self.write_fixed1616(z)


class PacketReader:
    """
    A unified BitStream Reader.
    Allows reading bits, bytes, and Wulfram types from a raw buffer.
    """
    def __init__(self, data: bytes):
        self._data = data
        self._total_bytes = len(data)
        self._byte_pos = 0
        self._bit_pos = 0 # 0 to 7

    def _check_eof(self, bits_needed=1):
        # Rough check to prevent reading past end
        bytes_needed = (bits_needed // 8)
        if self._byte_pos + bytes_needed > self._total_bytes:
            raise IndexError("End of Stream")

    def read_bits(self, num_bits: int) -> int:
        """Reads 'num_bits' and returns the integer value."""
        value = 0
        for _ in range(num_bits):
            if self._byte_pos >= self._total_bytes:
                return 0 # Or raise error
            
            # Extract bit at current position
            # (7 - bit_pos) because we read MSB first
            current_byte_val = self._data[self._byte_pos]
            bit = (current_byte_val >> (7 - self._bit_pos)) & 1
            
            # Shift previous value left and add new bit
            value = (value << 1) | bit
            
            # Advance cursor
            self._bit_pos += 1
            if self._bit_pos == 8:
                self._bit_pos = 0
                self._byte_pos += 1
        
        return value

    # ------------------------------------------------------------------
    # READ HELPERS
    # ------------------------------------------------------------------

    def read_remainder(self):
        """
        Returns all bytes remaining in the buffer from the current byte position.
        """
        # 1. Check if we are already at the end
        if self._byte_pos >= len(self._data):
            return b""

        # 2. Slice from the current byte cursor to the end
        result = self._data[self._byte_pos:]

        # 3. Fast-forward the cursor to the end (consume the stream)
        self._byte_pos = len(self._data)
        self._bit_pos = 0
        
        return result

    def read_byte(self) -> int:
        return self.read_bits(8)

    def read_int16(self) -> int:
        val = self.read_bits(16)
        # Sign extension logic if you need signed shorts:
        # if val & 0x8000: val -= 0x10000
        return val

    def read_int32(self) -> int:
        val = self.read_bits(32)
        
        # Check the 32nd bit (the sign bit)
        if val & 0x80000000: 
            # If set, subtract 2^32 to "wrap" it around to negative
            val -= 0x100000000
        
        return val

    def read_string(self) -> str:
        """Reads [Len 16] [Bytes...]"""
        length = self.read_int16()
        if length <= 0 or length > 4096: # Sanity check
            return ""
            
        # We read bytes manually to respect bit alignment 
        # (though usually strings are byte-aligned)
        raw_bytes = bytearray()
        for _ in range(length):
            raw_bytes.append(self.read_byte())
            
        # Remove null terminator if present at end
        if raw_bytes and raw_bytes[-1] == 0:
            raw_bytes.pop()
            
        return raw_bytes.decode('ascii', errors='ignore')
    
    def read_quantized_float(self, config) -> float:
        """
        Reads a quantized float using the provided TranslationConfig.
        Handles both Fixed Mode (Stats, Actions) and Dynamic Mode (Vectors).
        """
        # 1. Check if we are in Fixed Mode or Dynamic Mode
        if config.max_total_bits <= 0:
            # Fixed Mode: No Header is written. Priority is implicitly 0.
            priority = 0
            current_bits = config.precision_base_bits
            raw_val = self.read_bits(current_bits)
            return config.decompress(priority, raw_val)
        else:
            # Dynamic Mode: Read Header first.
            priority = self.read_bits(config.precision_header_bits)
            current_bits = config.precision_base_bits + priority
            raw_val = self.read_bits(current_bits)
            return config.decompress(priority, raw_val)