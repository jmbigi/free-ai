#!/usr/bin/env python3
"""
NCM GGUF Quantization Script

Quantizes an NCM GGUF model to lower precision formats using the gguf Python library.
"""

import sys
import os
import numpy as np
import gguf
from pathlib import Path
from typing import Dict, Any


def quantize_gguf(
    input_path: str,
    output_path: str,
    quantization: str = "Q4_K_M"
):
    """
    Quantize a GGUF model to the specified quantization type.
    
    Args:
        input_path: Path to input GGUF file (F16)
        output_path: Path to output quantized GGUF file
        quantization: Quantization type (Q4_K_M, Q3_K_M, Q2_K, Q8_0, IQ4_XS, IQ4_NL, etc.)
    """
    # Map string names to GGML quantization types
    qtype_map = {
        "Q4_K_M": gguf.GGMLQuantizationType.Q4_K_M,
        "Q4_K": gguf.GGMLQuantizationType.Q4_K,
        "Q4_0": gguf.GGMLQuantizationType.Q4_0,
        "Q4_1": gguf.GGMLQuantizationType.Q4_1,
        "Q3_K": gguf.GGMLQuantizationType.Q3_K,
        "Q2_K": gguf.GGMLQuantizationType.Q2_K,
        "Q8_0": gguf.GGMLQuantizationType.Q8_0,
        "Q5_K": gguf.GGMLQuantizationType.Q5_K,
        "Q6_K": gguf.GGMLQuantizationType.Q6_K,
        "IQ4_XS": gguf.GGMLQuantizationType.IQ4_XS,
        "IQ4_NL": gguf.GGMLQuantizationType.IQ4_NL,
        "IQ3_S": gguf.GGMLQuantizationType.IQ3_S,
        "IQ2_S": gguf.GGMLQuantizationType.IQ2_S,
        "IQ2_XXS": gguf.GGMLQuantizationType.IQ2_XXS,
        "IQ1_M": gguf.GGMLQuantizationType.IQ1_M,
        "IQ1_S": gguf.GGMLQuantizationType.IQ1_S,
        "MXFP4": gguf.GGMLQuantizationType.MXFP4,
        "NVFP4": gguf.GGMLQuantizationType.NVFP4,
        "F16": gguf.GGMLQuantizationType.F16,
        "F32": gguf.GGMLQuantizationType.F32,
    }
    
    if quantization not in qtype_map:
        print(f"Unknown quantization: {quantization}")
        print(f"Available: {list(qtype_map.keys())}")
        sys.exit(1)
    
    qtype = qtype_map[quantization]
    
    print(f"Loading GGUF model from {input_path}")
    
    # Read all tensors from input GGUF
    # We need to read the GGUF file metadata and tensors
    # Use gguf's tensor reading capability
    import struct
    
    # For now, let's use a simpler approach - read the model file directly
    # and extract tensors
    from gguf import GGUFReader
    
    reader = GGUFReader(input_path)
    
    print(f"Model architecture: {reader.architecture}")
    print(f"Number of tensors: {len(reader.tensors)}")
    
    # Create new GGUF writer
    writer = gguf.GGUFWriter(output_path, reader.architecture)
    
    # Copy all metadata (key-value pairs)
    for key, value in reader.fields.items():
        if key == "gguf.version":
            continue  # Will be set automatically
        try:
            if isinstance(value, list):
                writer.add_array(key, value)
            elif isinstance(value, str):
                writer.add_string(key, value)
            elif isinstance(value, bool):
                writer.add_bool(key, value)
            elif isinstance(value, int):
                writer.add_uint32(key, value)
            elif isinstance(value, float):
                writer.add_float32(key, value)
            else:
                print(f"Skipping unknown metadata type: {key} = {type(value)}")
        except Exception as e:
            print(f"Warning: Could not copy metadata {key}: {e}")
    
    # Quantize and add each tensor
    total_size_before = 0
    total_size_after = 0
    
    for i, tensor in enumerate(reader.tensors):
        name = tensor.name
        data = tensor.data
        
        # Get tensor info
        tensor_size_before = data.nbytes
        total_size_before += tensor_size_before
        
        # Quantize the data
        try:
            quantized_data = gguf.quantize(data, qtype)
            tensor_size_after = quantized_data.nbytes
            total_size_after += tensor_size_after
            
            # Add tensor to writer
            writer.add_tensor(name, quantized_data, raw_dtype=qtype)
            
            if (i + 1) % 50 == 0:
                print(f"  Quantized {i + 1}/{len(reader.tensors)} tensors...")
                
        except Exception as e:
            print(f"Warning: Could not quantize tensor {name}: {e}")
            # Add original data as fallback
            writer.add_tensor(name, data, raw_dtype=gguf.GGMLQuantizationType.F16)
            total_size_after += tensor_size_before
    
    print(f"Writing quantized GGUF to {output_path}")
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()
    
    # Report sizes
    import os
    before_size = os.path.getsize(input_path)
    after_size = os.path.getsize(output_path)
    
    print(f"\nQuantization complete!")
    print(f"  Input size:  {before_size / 1024 / 1024:.2f} MB")
    print(f"  Output size: {after_size / 1024 / 1024:.2f} MB")
    print(f"  Compression: {before_size / after_size:.2f}x")
    print(f"  Savings:     {(1 - after_size / before_size) * 100:.1f}%")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Quantize NCM GGUF model")
    parser.add_argument("input", help="Input GGUF file (F16)")
    parser.add_argument("output", help="Output quantized GGUF file")
    parser.add_argument("--quant", choices=["Q4_K_M", "Q4_K", "Q4_0", "Q3_K", "Q2_K", 
                                              "Q8_0", "Q5_K", "Q6_K", "IQ4_XS", "IQ4_NL",
                                              "IQ3_S", "IQ2_S", "IQ2_XXS", "IQ1_M", "IQ1_S"],
                       default="Q4_K_M", help="Quantization type")
    args = parser.parse_args()
    
    quantize_gguf(args.input, args.output, args.quant)


if __name__ == "__main__":
    main()