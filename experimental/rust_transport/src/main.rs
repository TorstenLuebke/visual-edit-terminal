//! Isolated binary-input transport probe, not a VT parser or terminal engine.
//! Its sole purpose is to validate lossless stdin transport and a simple
//! versioned reporting protocol before a licensed VT implementation is added.
use std::io::{self, Read};

const PROTOCOL: u32 = 1;

fn analyze(input: &[u8]) -> (usize, usize, usize, u64) {
    let mut escapes = 0;
    let mut newlines = 0;
    // FNV-1a checksum detects lost/altered bytes without extra crates.
    let mut digest: u64 = 0xcbf29ce484222325;
    for &byte in input {
        if byte == 0x1b { escapes += 1; }
        if byte == b'\n' { newlines += 1; }
        digest ^= byte as u64;
        digest = digest.wrapping_mul(0x100000001b3);
    }
    (input.len(), escapes, newlines, digest)
}

fn main() {
    let mut args = std::env::args().skip(1);
    let option = args.next();
    if args.next().is_some() {
        eprintln!("only one argument supported");
        std::process::exit(2);
    }
    match option.as_deref() {
        Some("--probe") => println!("{{\"protocol\":{},\"kind\":\"rust-transport\",\"vt_engine\":false}}", PROTOCOL),
        Some("--analyze") => {
            let mut input = Vec::new();
            if let Err(error) = io::stdin().read_to_end(&mut input) {
                eprintln!("failed to read input: {error}");
                std::process::exit(1);
            }
            let (bytes, escapes, newlines, hash) = analyze(&input);
            println!("{{\"protocol\":{},\"bytes\":{},\"escapes\":{},\"newlines\":{},\"fnv1a64\":\"{:016x}\"}}", PROTOCOL, bytes, escapes, newlines, hash);
        }
        _ => {
            eprintln!("usage: shelldeck-rust-transport-probe --probe|--analyze");
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::analyze;
    #[test]
    fn preserves_binary_bytes_and_counts_control_data() {
        let (length, escapes, newlines, digest) = analyze(b"\x00\xff\x1b[31mhi\n");
        assert_eq!((length, escapes, newlines), (10, 1, 1));
        assert_ne!(digest, 0);
    }
    #[test]
    fn checksum_depends_on_order() {
        assert_ne!(analyze(b"abc").3, analyze(b"cba").3);
    }
}
