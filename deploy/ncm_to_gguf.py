#!/usr/bin/env python3
"""
NCM PyTorch → GGUF Converter

Converts NCM (Next-Concept Modeling) PyTorch checkpoints to GGUF format.
NCM uses a coarse-to-fine transformer with multiscale residual VQ-VAE.
This converter maps NCM weights to GGUF format with custom architecture metadata.

Note: llama.cpp doesn't natively support NCM architecture yet.
This GGUF is for archival/portability; inference requires custom engine or NCM Python server.
"""

import sys
import os
import json
import struct
import torch
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Any

# Add NCM to path
NCM_HOME = os.environ.get("NCM_HOME", "/home/kubuntu/ncm")
sys.path.insert(0, NCM_HOME)

from models.next_concept import NextConceptTransformer
from models.vqvae import VQVAE
from omegaconf import OmegaConf

try:
    import gguf
except ImportError:
    print("ERROR: gguf package not installed. pip install gguf")
    sys.exit(1)


class NCMGGUFConverter:
    """Convert NCM PyTorch model to GGUF format."""
    
    def __init__(self, model_dir: str, output_path: str):
        self.model_dir = Path(model_dir)
        self.output_path = Path(output_path)
        self.gguf_writer = None
        self.config = None
        self.vqvae = None
        self.transformer = None
        
    def load_model(self):
        """Load NCM model from checkpoint."""
        print(f"Loading NCM model from {self.model_dir}")
        
        # Load config
        config_path = self.model_dir / "config.yaml"
        self.config = OmegaConf.load(config_path)
        
        # Load tokenizer (VQ-VAE)
        tokenizer_path = self.model_dir / "tokenizer.pt"
        tokenizer_state = torch.load(tokenizer_path, map_location="cpu", weights_only=False)
        
        # Build VQ-VAE from config with defaults for missing keys
        vqvae_config = self.config.tokenizer.vqvae
        vqvae_kwargs = {
            "in_vocab_size": vqvae_config.get("in_vocab_size", 30528),
            "context_length": vqvae_config.get("context_length", 128),
            "embed_dim": vqvae_config.get("embed_dim", 384),
            "vqvae_vocab_size": vqvae_config.get("vqvae_vocab_size", [8192]*13),
            "n_layers": vqvae_config.get("n_layers", 6),
            "vector_quantizer_config": vqvae_config.get("vector_quantizer_config", {}),
            "compression_factor": vqvae_config.get("compression_factor", 1),
            "dropout": vqvae_config.get("dropout", 0.1),
            "pre_quant_groupnorm": vqvae_config.get("pre_quant_groupnorm", 4),
            "pre_quant_dropout": vqvae_config.get("pre_quant_dropout", 0.0),
            "use_qk_norm": vqvae_config.get("use_qk_norm", True),
            "enc_layers": vqvae_config.get("enc_layers", 0),
            "enc_attn_window": vqvae_config.get("enc_attn_window", 0),
            "enc_conv_layers": vqvae_config.get("enc_conv_layers", 0),
            "enc_conv_kernel": vqvae_config.get("enc_conv_kernel", 3),
            "use_pos_emb": vqvae_config.get("enc_positional", False),
            "dec_positional": vqvae_config.get("dec_positional", True),
            "dec_layers": vqvae_config.get("dec_layers", 1),
            "pre_quant_norm_type": vqvae_config.get("pre_quant_norm_type", "group"),
        }
        self.vqvae = VQVAE(**vqvae_kwargs)
        
        # Load VQ-VAE weights
        if 'tokenizer' in tokenizer_state:
            self.vqvae.load_state_dict(tokenizer_state['tokenizer'], strict=True)
        else:
            self.vqvae.load_state_dict(tokenizer_state, strict=False)
        self.vqvae.eval()
        
        # Build Transformer
        model_config = self.config.model
        self.transformer = NextConceptTransformer(self.vqvae, model_config)
        
        # Load generator weights
        generator_path = self.model_dir / "generator.pt"
        generator_state = torch.load(generator_path, map_location="cpu", weights_only=False)
        
        if 'model' in generator_state:
            self.transformer.load_state_dict(generator_state['model'], strict=True)
        else:
            self.transformer.load_state_dict(generator_state, strict=False)
        self.transformer.eval()
        
        print(f"Model loaded successfully")
        print(f"  Transformer params: {sum(p.numel() for p in self.transformer.parameters())/1e6:.2f}M")
        print(f"  VQ-VAE params: {sum(p.numel() for p in self.vqvae.parameters())/1e6:.2f}M")
        
    def create_gguf_writer(self):
        """Initialize GGUF writer with NCM architecture metadata."""
        model_config = self.config.model
        vqvae_config = self.config.tokenizer.vqvae
        
        # Calculate total levels
        levels = self.vqvae.vq.levels if hasattr(self.vqvae.vq, 'levels') else \
                 self.config.model.get('levels', [1, 8, 16, 24, 32, 40, 52, 64, 76, 92, 108, 128])
        
        self.gguf_writer = gguf.GGUFWriter(str(self.output_path), "ncm")
        
        # Basic metadata
        self.gguf_writer.add_name("ncm-instruct-725m")
        self.gguf_writer.add_file_type(gguf.GGMLQuantizationType.F16)
        
        # Extract levels from VQ config
        vq_levels_cfg = vqvae_config.vector_quantizer_config.levels
        if hasattr(vq_levels_cfg, 'manual_levels'):
            levels = list(vq_levels_cfg.manual_levels)
        elif hasattr(vq_levels_cfg, 'levels'):
            levels = list(vq_levels_cfg.levels)
        else:
            levels = [1, 8, 16, 24, 32, 40, 52, 64, 76, 92, 108, 128]
        
        # Architecture metadata
        self.gguf_writer.add_context_length(self.config.model.prefix_len + sum(levels))
        self.gguf_writer.add_embedding_length(vqvae_config.embed_dim)
        self.gguf_writer.add_block_count(self.config.model.n_layer)
        self.gguf_writer.add_feed_forward_length(4 * self.config.model.n_embd)  # typical
        self.gguf_writer.add_head_count(self.config.model.n_head)
        self.gguf_writer.add_layer_norm_rms_eps(1e-5)
        
        # NCM-specific metadata
        self.gguf_writer.add_uint32("ncm.query_level0", int(self.config.model.query_level0))
        self.gguf_writer.add_uint32("ncm.predict_level0", int(self.config.model.predict_level0))
        self.gguf_writer.add_uint32("ncm.num_levels", len(levels))
        self.gguf_writer.add_string("ncm.levels", str(levels))
        self.gguf_writer.add_uint32("ncm.prefix_len", self.config.model.prefix_len)
        self.gguf_writer.add_string("ncm.attn_pattern", self.config.model.attn_pattern)
        self.gguf_writer.add_bool("ncm.use_rope", self.config.model.use_rope)
        self.gguf_writer.add_uint32("ncm.rope_base", self.config.model.rope_base)
        
        # VQ-VAE metadata
        self.gguf_writer.add_uint32("ncm.vqvae.embed_dim", vqvae_config.embed_dim)
        self.gguf_writer.add_string("ncm.vqvae.levels", str(levels))
        self.gguf_writer.add_string("ncm.vqvae.vocab_sizes", str(self.config.model.vocab_size))
        
        # Generation config
        gen_config = self.config.generation
        self.gguf_writer.add_float32("ncm.gen.temperature", gen_config.temperature)
        self.gguf_writer.add_float32("ncm.gen.top_p", gen_config.top_p)
        self.gguf_writer.add_uint32("ncm.gen.top_k", gen_config.top_k)
        self.gguf_writer.add_float32("ncm.gen.cfg_scale", gen_config.cfg_scale)
        
    def add_vqvae_tensors(self):
        """Add VQ-VAE tensors to GGUF."""
        print("Adding VQ-VAE tensors...")
        
        # Encoder
        encoder = self.vqvae.encoder
        for name, param in encoder.named_parameters():
            self._add_tensor(f"vqvae.encoder.{name}", param)
            
        # Decoder
        decoder = self.vqvae.decoder
        for name, param in decoder.named_parameters():
            self._add_tensor(f"vqvae.decoder.{name}", param)
            
        # VQ
        vq = self.vqvae.vq
        for i, emb in enumerate(vq.embeddings):
            self._add_tensor(f"vqvae.vq.embeddings.{i}.weight", emb.weight)
            
        # Pre-quant norm
        if self.vqvae.pre_quant_norm is not None:
            for name, param in self.vqvae.pre_quant_norm.named_parameters():
                self._add_tensor(f"vqvae.pre_quant_norm.{name}", param)
                
        print("  VQ-VAE tensors added")
        
    def add_transformer_tensors(self):
        """Add Transformer tensors to GGUF."""
        print("Adding Transformer tensors...")
        
        for name, param in self.transformer.named_parameters():
            # Map NCM names to GGUF-friendly names
            gguf_name = f"transformer.{name}"
            self._add_tensor(gguf_name, param)
            
        print("  Transformer tensors added")
        
    def _add_tensor(self, name: str, tensor: torch.Tensor):
        """Add a tensor to GGUF writer."""
        # Convert to float16 for storage efficiency
        if tensor.dtype == torch.float32:
            tensor = tensor.half()
        elif tensor.dtype == torch.bfloat16:
            tensor = tensor.float().half()
            
        # Convert to numpy
        np_array = tensor.detach().cpu().numpy()
        
        # Determine quantization type
        if np_array.dtype == np.float16:
            qtype = gguf.GGMLQuantizationType.F16
        elif np_array.dtype == np.float32:
            qtype = gguf.GGMLQuantizationType.F32
        else:
            qtype = gguf.GGMLQuantizationType.F16
            np_array = np_array.astype(np.float16)
            
        self.gguf_writer.add_tensor(name, np_array, raw_dtype=qtype)
        
    def write(self):
        """Write GGUF file."""
        print(f"Writing GGUF to {self.output_path}")
        self.gguf_writer.write_header_to_file()
        self.gguf_writer.write_kv_data_to_file()
        self.gguf_writer.write_tensors_to_file()
        self.gguf_writer.close()
        print("GGUF write complete!")
        
    def convert(self):
        """Run full conversion pipeline."""
        self.load_model()
        self.create_gguf_writer()
        self.add_vqvae_tensors()
        self.add_transformer_tensors()
        self.write()
        print(f"Conversion complete: {self.output_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Convert NCM PyTorch checkpoint to GGUF")
    parser.add_argument("model_dir", help="NCM model directory (with config.yaml, generator.pt, tokenizer.pt)")
    parser.add_argument("output", help="Output GGUF file path")
    parser.add_argument("--quantize", choices=["q4_k_m", "q3_k_m", "q2_k", "q8_0", "int4", "int8"], 
                       help="Quantize after conversion (requires llama-quantize)")
    args = parser.parse_args()
    
    converter = NCMGGUFConverter(args.model_dir, args.output)
    converter.convert()
    
    if args.quantize:
        print(f"Quantizing to {args.quantize}...")
        import subprocess
        subprocess.run(["llama-quantize", args.output, 
                       args.output.replace(".gguf", f".{args.quantize}.gguf"),
                       args.quantize], check=True)


if __name__ == "__main__":
    main()