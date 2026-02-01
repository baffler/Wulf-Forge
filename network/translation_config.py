import struct

class TranslationConfig:
    def __init__(self):
        self.precision_header_bits = 0
        self.precision_base_bits = 0
        self.max_total_bits = 0
        self.min_value = 0.0
        self.max_value = 0.0
        self.range = 0.0

    def configure(self, header_bits, max_total_bits, max_val_str, range_val_str):
        self.precision_header_bits = int(header_bits)
        self.max_total_bits = int(max_total_bits)
        self.max_value = float(max_val_str)
        self.range = float(range_val_str)
        self.min_value = self.max_value - self.range
        
        # Calculate Base Bits (The critical C++ math)
        if self.max_total_bits <= 0:
            self.precision_base_bits = self.precision_header_bits
        else:
            # Calculate Resolution (2^N)
            quantization_resolution = 1 << self.precision_header_bits
            diff = self.max_total_bits - quantization_resolution
            self.precision_base_bits = diff + 1
            if self.precision_base_bits < 1:
                self.precision_base_bits = 1

    def compress(self, float_val, priority=3):
        """
        Returns: (header_value, compressed_int, num_bits)
        Inverse compression to match 'Unpack_Float_From_Int'.
        """
        # 1. Determine Total Bits (The Denominator Logic)
        if self.max_total_bits <= 0:
            # Fixed Mode (Stats)
            current_bits = self.precision_base_bits
            priority = 0 # Force 0 for fixed
        else:
            # Dynamic Mode (Vectors)
            # Clamp priority to the header size (e.g., 2 bits = max 3)
            max_p = (1 << self.precision_header_bits) - 1
            if priority > max_p: priority = max_p
            current_bits = self.precision_base_bits + priority

        # 2. SPECIAL CASE: Absolute Zero
        # C++: if (!raw_integer_value) return 0.0;
        # If the value is exactly 0.0, we send 0 to save precision logic.
        if float_val == 0.0:
            return priority, 0, current_bits

        # 3. Calculate Denominator (Max Steps)
        # C++: (2 * (1 << (bit_count - 1)) - 2)
        # Simplified: (1 << current_bits) - 2
        # This gives us the range of valid integers [1, Denominator + 1]
        denom = (1 << current_bits) - 2
        if denom <= 0: denom = 1 # Safety

        # 4. Clamp Input
        if float_val > self.max_value: float_val = self.max_value
        if float_val < self.min_value: float_val = self.min_value

        # 5. Inverse Quantization Formula
        # C++ Result = Max - (Raw - 1) * Range / Denom
        # Therefore: Raw - 1 = (Max - Result) * Denom / Range
        # Raw = ((Max - Result) * Denom / Range) + 1
        
        if self.range == 0:
            raw_val = 1
        else:
            # How far are we from the Max?
            delta = self.max_value - float_val
            
            # Scale that delta to integer steps
            scaled = (delta * denom) / self.range
            raw_val = int(scaled) + 1

        return priority, raw_val, current_bits
    
    def decompress(self, priority: int, raw_val: int) -> float:
        """
        Reconstructs the float value from the raw integer and priority header.
        Matches C++ 'Unpack_Float_From_Int'.
        """
        # 1. Determine Total Bits
        if self.max_total_bits <= 0:
            current_bits = self.precision_base_bits
        else:
            current_bits = self.precision_base_bits + priority

        # 2. Special Case: Zero
        if raw_val == 0:
            return 0.0

        # 3. Calculate Denominator
        denom = (1 << current_bits) - 2
        if denom <= 0: denom = 1

        # 4. Calculate Float
        if self.range == 0:
            return self.max_value
        
        # Formula: Result = Max - ((Raw - 1) * Range / Denom)
        scaled = raw_val - 1
        delta = (scaled * self.range) / denom
        result = self.max_value - delta

        return result

# --- GLOBAL CONFIGURATION ---
# --- THE SOURCE OF TRUTH (DATA) ---

# Defaults: A generic scalar config
SCALAR_DEFAULT = {"head": 16, "total": 0, "max": "1000.0", "range": "2000.0"}

# Initialize all 28 slots with default scalar settings
GLOBAL_CONFIGS = [SCALAR_DEFAULT.copy() for _ in range(28)]

# --- SCALAR OVERRIDES (Indices 0-15) ---
# Index 1: Weapon ID (5 bits raw)
GLOBAL_CONFIGS[1] = {"head": 5, "total": 0, "max": "0.0", "range": "0.0"}

# --- ID BITS (Crucial for Entity Def & Team) ---
# You found that Index 2 & 3 determine the bit count for these IDs.
# We set them to 8 bits (standard byte).
# Logic: max_total=0 means 'head' is the bit count.
GLOBAL_CONFIGS[2] = {"head": 8, "total": 0, "max": "0.0", "range": "0.0"} # Unit Type
GLOBAL_CONFIGS[3] = {"head": 8, "total": 0, "max": "0.0", "range": "0.0"} # Team ID

GLOBAL_CONFIGS[4] = {"head": 8, "total": 0, "max": "0.0", "range": "0.0"} # Unit Type Stored within Cargo

# Index 5: Health (0.0 to 1.0)
# --- 1. FIXED STAT CONFIG (Health) ---
# Logic: "I want exactly 10 bits of data. No header."
# Setup: head=10, total=0.
GLOBAL_CONFIGS[5] = {"head": 10, "total": 0, "max": "1.0", "range": "1.0"}

# Index 8: Energy (0.0 to 1.0)
GLOBAL_CONFIGS[8] = {"head": 10, "total": 0, "max": "1.0", "range": "1.0"}

# Index 13 & 14: Extra Vitals (e.g. Shield/Stamina)
GLOBAL_CONFIGS[13] = {"head": 8, "total": 0, "max": "1.0", "range": "1.0"}
GLOBAL_CONFIGS[14] = {"head": 8, "total": 0, "max": "1.0", "range": "1.0"}

# --- VECTOR TEMPLATES (High Precision for Testing) ---
# We use max_total=16 bits. Header=4 bits. 
# This gives a base of ~13 bits + header = very smooth.

# --- 2. DYNAMIC VECTOR CONFIG (Position) ---
# Logic: "I want between 13 and 16 bits, controlled by a 4-bit header."
# Setup: head=4, total=16.
# Math: Range of header is 4 (0-3). Base = 16 - 4 + 1 = 13.
# Result: Header 0=13 bits, Header 3=16 bits.
VEC_POS  = {"head": 4, "total": 16, "max": "8192.0", "range": "16384.0"} # +/- 8192

# +/- 200 *should* enough for tank velocity
VEC_VEL  = {"head": 4, "total": 16, "max": "1000.0",  "range": "2000.0"}  # +/- 1000

# Increased to cover 2*PI (approx 6.28). 
# Range 12.6 allows for -6.3 to +6.3, covering full rotation safely.
VEC_ROT  = {"head": 4, "total": 16, "max": "6.3",    "range": "12.6"}    # +/- 2*PI

# Angular velocity of 10 rads/sec should be fast enough (~1.5 full spins/sec)
VEC_SPIN = {"head": 4, "total": 16, "max": "200.0",   "range": "400.0"}   # +/- 10.0

# --- APPLY VECTORS TO BANKS (Indices 16-27) ---
# Bank 0 (16-19), Bank 1 (20-23), Bank 2 (24-27)
for bank in range(3):
    start_idx = 16 + (bank * 4)
    GLOBAL_CONFIGS[start_idx + 0] = VEC_POS
    GLOBAL_CONFIGS[start_idx + 1] = VEC_VEL
    GLOBAL_CONFIGS[start_idx + 2] = VEC_ROT
    GLOBAL_CONFIGS[start_idx + 3] = VEC_SPIN

# --- 3. EXPORTED INSTANCES ---
# Your code imports these to compress data. They are built from the config above.

def _make(cfg):
    c = TranslationConfig()
    c.configure(cfg['head'], cfg['total'], cfg['max'], cfg['range'])
    return c

COMPRESSOR_POS = _make(VEC_POS)
COMPRESSOR_VEL = _make(VEC_VEL)
COMPRESSOR_ROT = _make(VEC_ROT)
COMPRESSOR_SPIN = _make(VEC_SPIN)
COMPRESSOR_STAT = _make(GLOBAL_CONFIGS[5]) # Health/Energy

# Also export the ID bit counts so the packet writer doesn't need to guess
ID_BITS_UNIT = GLOBAL_CONFIGS[2]['head']
ID_BITS_TEAM = GLOBAL_CONFIGS[3]['head']
ID_BITS_UNIT_CARGO = GLOBAL_CONFIGS[4]['head']
BANK_SELECTOR_BITS = GLOBAL_CONFIGS[0]['head']


# Simple Cache for reusing TranslationConfig objects for Action lookups
_config_cache = {}

def get_config_by_index(index: int) -> TranslationConfig:
    """Returns the TranslationConfig object for a given global table index."""
    if index < 0 or index >= len(GLOBAL_CONFIGS):
        return _make(SCALAR_DEFAULT) # Fallback
    
    if index not in _config_cache:
        _config_cache[index] = _make(GLOBAL_CONFIGS[index])
    
    return _config_cache[index]