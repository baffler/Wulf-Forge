import math

class FloatCompressor:
    """
    Handles the quantization of floats based on the Server Config.
    Matches the logic of the client's 'Snapshot_Read_Vector'.
    """
    def __init__(self, max_val, range_val, max_bits):
        self.max_val = float(max_val)
        self.range_val = float(range_val)
        self.min_val = self.max_val - self.range_val
        
        # Calculate Base Bits based on the formula: 
        # Base = Total - (1 << HeaderBits) + 1
        # We assume standard 2-bit headers for now.
        header_res = (1 << 2) # 4
        self.base_bits = (max_bits - header_res) + 1
        
        # Pre-calc max integer values for clamping
        # Level 3 (Max Precision) uses 'max_bits' - 2 (for header)
        # Wait! The bit logic is: Total Bits written = Header(2) + Data(N)
        # If Config says "12 bits total", and Header takes 2...
        # We write 10 bits of data.
        self.max_precision_data_bits = max_bits - 2
        self.max_int_step = (1 << self.max_precision_data_bits) - 1

    def compress(self, value):
        """
        Compresses a float into (Header, Data, NumDataBits).
        For this prototype, we ALWAYS use Max Precision (Header 3).
        """
        # 1. Clamp to World Bounds
        if value > self.max_val: value = self.max_val
        if value < self.min_val: value = self.min_val

        # 2. Normalize (0.0 to 1.0)
        # Math: (Value - Min) / Range
        normalized = (value - self.min_val) / self.range_val

        # 3. Quantize to Integer
        # We map 0.0-1.0 to 0-MaxStep
        quantized = int(normalized * self.max_int_step)

        # 4. Return tuple: (HeaderValue, QuantizedInt, BitCountForInt)
        # Header 3 means "Max Zoom"
        return (3, quantized, self.max_precision_data_bits)
    
def compress_fixed(self, value):
        """
        Compresses a float into a raw integer without a header.
        Used for Health/Energy which are strictly fixed-bit.
        """
        # 1. Clamp
        if value > self.max_val: value = self.max_val
        if value < self.min_val: value = self.min_val

        # 2. Normalize (0.0 to 1.0)
        # Avoid division by zero
        if self.range_val == 0:
            return 0
            
        normalized = (value - self.min_val) / self.range_val

        # 3. Quantize
        # We use the Base Bits (calculated from max_bits in __init__)
        # Note: For fixed mode, ensure your compressor was init'd with the fixed bit count!
        max_step = (1 << self.max_precision_data_bits) - 1 # Use the bit count passed in init
        quantized = int(normalized * max_step)
        
        return quantized

# --- GLOBAL CONFIGURATION (Must match the Translation Packet!) ---
# Index 0: Position (12 bits, Range 8192)
COMPRESSOR_POS = FloatCompressor(4096.0, 8192.0, 20)

# Index 1: Velocity (10 bits, Range 400)
COMPRESSOR_VEL = FloatCompressor(4096.0, 8192.0, 20)

# Index 2: Rotation (8 bits, Range 2.0)
COMPRESSOR_ROT = FloatCompressor(4096.0, 8192.0, 20)

# Index 5 & 8: 8 bits, Range 1.0 (0.0 to 1.0)
# We pass '8' as the bits. The logic in __init__ subtracts 2 for header, 
# so we should actually pass '10' to get 8 data bits?
# WAIT: The class logic subtracts 2 because it assumes dynamic.
# Let's just make a specific 'FixedCompressor' to be safe.
class FixedCompressor:
    def __init__(self, max_val, range_val, bit_count):
        self.max_val = max_val
        self.min_val = max_val - range_val
        self.range_val = range_val
        self.max_step = (1 << bit_count) - 1
        self.bit_count = bit_count

    def compress(self, value):
        if value > self.max_val: value = self.max_val
        if value < self.min_val: value = self.min_val
        if self.range_val == 0: return 0
        normalized = (value - self.min_val) / self.range_val
        return int(normalized * self.max_step)

COMPRESSOR_STAT = FixedCompressor(1.0, 1.0, 10)