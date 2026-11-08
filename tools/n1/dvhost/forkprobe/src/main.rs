//! Exercise the pinned `doppingkoala/dovi_tool` fork through its real API.
//!
//! The call sequence mirrors what the Kodi DM conversion patch does per frame:
//!
//!   Kodi (BitstreamConverter::processDoviRpu):
//!     dovi_parse_unspec62_nalu(buf, len)      -> parse the decoder NAL
//!     dovi_rpu_get_header()                   -> read the guessed profile
//!     profile 7        -> dovi_convert_rpu_with_mode(rpu, 2)   (To81)
//!     profile 5 or 8   -> no conversion, only "processed = true"
//!     dovi_write_unspec62_nalu(rpu)           -> bytes handed back to the decoder
//!
//! For every frame we dump:
//!   * the NAL bytes the writer produced (what the decoder would receive),
//!   * `write_rpu()` which is exactly `0xFF || DM` (no NAL header, no escaping),
//!   * the serde JSON of the RPU so an independent Python rebuild can be done,
//!   * for profile 7, a control run without conversion, to prove the branch ran.
//!
//! Nothing here is a reimplementation: every byte comes from the fork itself.

use dolby_vision::rpu::dovi_rpu::DoviRpu;
use std::fmt::Write as _;
use std::fs;
use std::io::Write as _;
use std::path::{Path, PathBuf};

struct FrameOut {
    index: usize,
    profile_in: u8,
    profile_out: u8,
    converted: bool,
    /// `header.reserved_zero_3bits == 1` in the fork => compressed DM payload.
    compressed: bool,
    rpu_type: u8,
    dm_present: bool,
    has_mapping: bool,
    nal_len: usize,
    rpu_len: usize,
    control_rpu_len: Option<usize>,
    /// 1 when the unconverted bytes are identical to the converted ones.
    control_same: Option<bool>,
}

fn split_nals(data: &[u8]) -> Vec<&[u8]> {
    // Fixtures are Annex-B style RPU bins: 00 00 00 01 (or 00 00 01) between NALs.
    let mut out = Vec::new();
    let mut i = 0usize;
    let mut start = None;
    while i + 3 <= data.len() {
        let sc4 = i + 4 <= data.len() && data[i..i + 4] == [0, 0, 0, 1];
        let sc3 = data[i..i + 3] == [0, 0, 1];
        if sc4 || sc3 {
            if let Some(s) = start {
                out.push(&data[s..i]);
            }
            i += if sc4 { 4 } else { 3 };
            start = Some(i);
        } else {
            i += 1;
        }
    }
    if let Some(s) = start {
        if s < data.len() {
            out.push(&data[s..]);
        }
    }
    if out.is_empty() && !data.is_empty() {
        out.push(data);
    }
    out
}

/// Kodi hands the parser the NAL unit including its 2-byte HEVC NAL header.
fn kodi_input(body: &[u8]) -> Vec<u8> {
    // Original Dolby RPU body starts with rpu_prefix 0x19; converted bodies start
    // with 0xFF. Both are seen by Kodi with `7C 01` in front.
    if body.first() == Some(&0x19) || body.first() == Some(&0xFF) {
        let mut v = Vec::with_capacity(body.len() + 2);
        v.extend_from_slice(&[0x7C, 0x01]);
        v.extend_from_slice(body);
        v
    } else {
        body.to_vec()
    }
}

fn write_out(dir: &Path, name: &str, bytes: &[u8]) -> std::io::Result<()> {
    let mut f = fs::File::create(dir.join(name))?;
    f.write_all(bytes)
}

fn process_fixture(path: &Path, out_root: &Path, manifest: &mut String) -> (usize, usize) {
    let data = fs::read(path).unwrap_or_default();
    let name = path.file_name().unwrap().to_string_lossy().to_string();
    let dir = out_root.join(&name);
    fs::create_dir_all(&dir).expect("create fixture dir");

    let mut frames = 0usize;
    let mut errors = 0usize;
    for (idx, body) in split_nals(&data).into_iter().enumerate() {
        let input = kodi_input(body);
        let parsed = DoviRpu::parse_unspec62_nalu(&input);
        let mut rpu = match parsed {
            Ok(r) => r,
            Err(e) => {
                errors += 1;
                writeln!(manifest, "FRAME fixture={} idx={} parse_error={}", name, idx,
                         e.to_string().replace('\n', " ")).unwrap();
                continue;
            }
        };

        let profile_in = rpu.dovi_profile;
        let compressed = rpu.header.reserved_zero_3bits == 1;
        let rpu_type = rpu.header.rpu_type;
        let dm_present = rpu.header.vdr_dm_metadata_present_flag;
        let has_mapping = rpu.rpu_data_mapping.is_some();

        // Kodi DM conversion patch conditions.
        let converted = match profile_in {
            7 => match rpu.convert_with_mode(2u8) {
                Ok(()) => true,
                Err(e) => {
                    errors += 1;
                    writeln!(manifest, "FRAME fixture={} idx={} convert_error={}", name, idx,
                             e.to_string().replace('\n', " ")).unwrap();
                    continue;
                }
            },
            // profile 5 / 8: the patch only marks the RPU as processed.
            _ => false,
        };
        let profile_out = rpu.dovi_profile;

        let nal = match rpu.write_hevc_unspec62_nalu() {
            Ok(v) => v,
            Err(e) => {
                errors += 1;
                writeln!(manifest, "FRAME fixture={} idx={} write_nal_error={}", name, idx,
                         e.to_string().replace('\n', " ")).unwrap();
                continue;
            }
        };
        let rpu_bytes = match rpu.write_rpu() {
            Ok(v) => v,
            Err(e) => {
                errors += 1;
                writeln!(manifest, "FRAME fixture={} idx={} write_rpu_error={}", name, idx,
                         e.to_string().replace('\n', " ")).unwrap();
                continue;
            }
        };
        let json = serde_json::to_vec(&rpu).expect("serialize rpu");

        write_out(&dir, &format!("f{:03}.nal", idx), &nal).unwrap();
        write_out(&dir, &format!("f{:03}.rpu", idx), &rpu_bytes).unwrap();
        write_out(&dir, &format!("f{:03}.json", idx), &json).unwrap();
        write_out(&dir, &format!("f{:03}.in", idx), &input).unwrap();

        // Control: profile 7 without conversion, from a fresh parse.
        let mut control_len = None;
        let mut control_same = None;
        if profile_in == 7 {
            if let Ok(fresh) = DoviRpu::parse_unspec62_nalu(&input) {
                if let Ok(bytes) = fresh.write_rpu() {
                    control_same = Some(bytes == rpu_bytes);
                    write_out(&dir, &format!("f{:03}.ctl.rpu", idx), &bytes).unwrap();
                    control_len = Some(bytes.len());
                }
            }
        }

        let fo = FrameOut {
            index: idx,
            profile_in,
            profile_out,
            converted,
            compressed,
            rpu_type,
            dm_present,
            has_mapping,
            nal_len: nal.len(),
            rpu_len: rpu_bytes.len(),
            control_rpu_len: control_len,
            control_same,
        };
        writeln!(
            manifest,
            "FRAME fixture={} idx={} profile_in={} profile_out={} converted={} compressed={} \
             rpu_type={} dm_present={} mapping={} nal_len={} rpu_len={} ctl_rpu_len={} \
             ctl_same={} dir={}",
            name,
            fo.index,
            fo.profile_in,
            fo.profile_out,
            if fo.converted { 1 } else { 0 },
            if fo.compressed { 1 } else { 0 },
            fo.rpu_type,
            if fo.dm_present { 1 } else { 0 },
            if fo.has_mapping { 1 } else { 0 },
            fo.nal_len,
            fo.rpu_len,
            fo.control_rpu_len.map(|v| v.to_string()).unwrap_or_else(|| "-".into()),
            fo.control_same
                .map(|v| if v { "1" } else { "0" })
                .unwrap_or("-"),
            dir.file_name().unwrap().to_string_lossy(),
        )
        .unwrap();
        frames += 1;
    }
    writeln!(manifest, "FIXTURE name={} frames={} errors={}", name, frames, errors).unwrap();
    (frames, errors)
}

fn main() {
    let mut assets = PathBuf::new();
    let mut out = PathBuf::new();
    let mut select = String::new();
    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "--assets" => {
                assets = PathBuf::from(&argv[i + 1]);
                i += 2;
            }
            "--out" => {
                out = PathBuf::from(&argv[i + 1]);
                i += 2;
            }
            "--select" => {
                select = argv[i + 1].clone();
                i += 2;
            }
            other => panic!("unknown argument {other}"),
        }
    }
    if assets.as_os_str().is_empty() || out.as_os_str().is_empty() {
        panic!("usage: dv_fork_probe --assets <dir> --out <dir> [--select a,b]");
    }
    fs::create_dir_all(&out).expect("create out dir");

    let wanted: Vec<String> = select
        .split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();

    let mut files: Vec<PathBuf> = fs::read_dir(&assets)
        .expect("read assets dir")
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().map(|e| e == "bin").unwrap_or(false))
        .collect();
    files.sort();

    let mut manifest = String::new();
    let mut total_frames = 0usize;
    let mut total_errors = 0usize;
    let mut used = 0usize;
    for f in &files {
        let name = f.file_name().unwrap().to_string_lossy().to_string();
        if !wanted.is_empty() && !wanted.iter().any(|w| name.contains(w.as_str())) {
            continue;
        }
        let (frames, errors) = process_fixture(f, &out, &mut manifest);
        if frames > 0 {
            used += 1;
        }
        total_frames += frames;
        total_errors += errors;
    }
    writeln!(
        manifest,
        "SUMMARY fixtures_used={} frames={} errors={} fork_crate=dolby_vision",
        used, total_frames, total_errors
    )
    .unwrap();
    fs::write(out.join("manifest.txt"), manifest.as_bytes()).expect("write manifest");
    print!("{}", manifest);
    if used == 0 || total_frames == 0 {
        eprintln!("probe produced no frames");
        std::process::exit(2);
    }
    // Upstream fixtures deliberately include malformed inputs, so per-frame
    // errors are reported (and counted by check_fork_run.py) instead of
    // failing the whole probe.
    if total_errors > 0 {
        eprintln!("probe parsed {} frames with {} errors", total_frames, total_errors);
    }
}
