//! A tiny FIT encoder for synthetic test fixtures. It writes just enough of
//! the protocol (header, definition and data messages, CRCs) for the
//! importer's parser to read. No real GPS data: positions are made up.

#![allow(dead_code)]

/// Seconds between the Unix epoch and the FIT epoch (1989-12-31T00:00:00Z).
pub const FIT_EPOCH_OFFSET: i64 = 631_065_600;

pub const MESG_FILE_ID: u16 = 0;
pub const MESG_LAP: u16 = 19;
pub const MESG_RECORD: u16 = 20;
/// A manufacturer-specific message number; parsers report it as `unknown_*`.
pub const MESG_PRIVATE: u16 = 0xFF00;

pub const ENUM: u8 = 0x00;
pub const SINT8: u8 = 0x01;
pub const UINT8: u8 = 0x02;
pub const UINT16: u8 = 0x84;
pub const SINT32: u8 = 0x85;
pub const UINT32: u8 = 0x86;

/// One field of a data message: field number, base type, raw value. The
/// value is written in the base type's width; use the type's invalid value
/// (e.g. `0xFF` for `UINT8`) to mark it missing.
#[derive(Clone, Copy)]
pub struct Field {
    pub num: u8,
    pub base_type: u8,
    pub raw: i64,
}

pub fn field(num: u8, base_type: u8, raw: i64) -> Field {
    Field {
        num,
        base_type,
        raw,
    }
}

fn size_of(base_type: u8) -> u8 {
    match base_type {
        ENUM | SINT8 | UINT8 => 1,
        UINT16 => 2,
        SINT32 | UINT32 => 4,
        other => panic!("unsupported base type {other:#x}"),
    }
}

/// Builds a FIT file message by message. Every `message` call writes a
/// fresh definition on local type 0 followed by one data message.
#[derive(Default)]
pub struct FitWriter {
    body: Vec<u8>,
}

impl FitWriter {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn message(mut self, global: u16, fields: &[Field]) -> Self {
        self.define(global, fields, &[]);
        self.data(fields, &[]);
        self
    }

    /// A message whose definition declares developer fields
    /// `(field_number, size, developer_data_index)`, without any preceding
    /// `developer_data_id` / `field_description`: the shape of
    /// fitparser issue #58.
    pub fn message_with_undescribed_dev_fields(
        mut self,
        global: u16,
        fields: &[Field],
        dev: &[(u8, u8, u8)],
    ) -> Self {
        self.define(global, fields, dev);
        let dev_bytes: Vec<u8> = dev
            .iter()
            .flat_map(|&(_, size, _)| vec![0u8; size as usize])
            .collect();
        self.data(fields, &dev_bytes);
        self
    }

    fn define(&mut self, global: u16, fields: &[Field], dev: &[(u8, u8, u8)]) {
        let header = if dev.is_empty() { 0x40 } else { 0x60 };
        self.body.push(header);
        self.body.push(0); // reserved
        self.body.push(0); // little endian
        self.body.extend_from_slice(&global.to_le_bytes());
        self.body.push(fields.len() as u8);
        for f in fields {
            self.body
                .extend_from_slice(&[f.num, size_of(f.base_type), f.base_type]);
        }
        if !dev.is_empty() {
            self.body.push(dev.len() as u8);
            for &(num, size, index) in dev {
                self.body.extend_from_slice(&[num, size, index]);
            }
        }
    }

    fn data(&mut self, fields: &[Field], dev_bytes: &[u8]) {
        self.body.push(0x00);
        for f in fields {
            let bytes = f.raw.to_le_bytes();
            self.body
                .extend_from_slice(&bytes[..size_of(f.base_type) as usize]);
        }
        self.body.extend_from_slice(dev_bytes);
    }

    pub fn finish(self) -> Vec<u8> {
        let mut out = Vec::with_capacity(self.body.len() + 16);
        out.push(14); // header size
        out.push(0x20); // protocol 2.0
        out.extend_from_slice(&2132u16.to_le_bytes()); // profile version
        out.extend_from_slice(&(self.body.len() as u32).to_le_bytes());
        out.extend_from_slice(b".FIT");
        let header_crc = crc(&out);
        out.extend_from_slice(&header_crc.to_le_bytes());
        out.extend_from_slice(&self.body);
        let file_crc = crc(&out);
        out.extend_from_slice(&file_crc.to_le_bytes());
        out
    }
}

/// FIT CRC-16 (the nibble-table variant from the FIT SDK).
pub fn crc(bytes: &[u8]) -> u16 {
    const TABLE: [u16; 16] = [
        0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401, 0xA001, 0x6C00, 0x7800,
        0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
    ];
    let mut crc = 0u16;
    for &b in bytes {
        let tmp = TABLE[(crc & 0xF) as usize];
        crc = (crc >> 4) & 0x0FFF;
        crc = crc ^ tmp ^ TABLE[(b & 0xF) as usize];
        let tmp = TABLE[(crc & 0xF) as usize];
        crc = (crc >> 4) & 0x0FFF;
        crc = crc ^ tmp ^ TABLE[((b >> 4) & 0xF) as usize];
    }
    crc
}

/// FIT timestamp for a Unix time.
pub fn fit_time(unix: i64) -> i64 {
    unix - FIT_EPOCH_OFFSET
}

/// Degrees to FIT semicircles.
pub fn semicircles(deg: f64) -> i64 {
    (deg * 2f64.powi(31) / 180.0).round() as i64
}
