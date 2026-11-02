mod protocol;
use base64::{engine::general_purpose::STANDARD, Engine};
use serde_json::{json, Value};
use std::io::{self, Read, Write};
#[derive(Clone, Default, Debug)]
struct Cell {
    text: String,
    kind: String,
    formula: Option<String>,
    style: String,
    span: usize,
}
type Grid = Vec<Vec<Cell>>;
fn esc(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}
fn config() -> Value {
    std::env::var("JIETUBA_PLUGIN_CONFIG")
        .ok()
        .and_then(|p| std::fs::read(p).ok())
        .filter(|s| s.len() < 65536)
        .and_then(|s| serde_json::from_slice(&s).ok())
        .unwrap_or(json!({}))
}
fn decoded(raw: &str) -> Option<String> {
    let bytes = STANDARD.decode(raw).ok()?;
    let text = if bytes.starts_with(&[255, 254]) || bytes.starts_with(&[b'<', 0]) {
        let start = if bytes.starts_with(&[255, 254]) { 2 } else { 0 };
        String::from_utf16(
            &bytes[start..]
                .chunks_exact(2)
                .map(|b| u16::from_le_bytes([b[0], b[1]]))
                .collect::<Vec<_>>(),
        )
        .ok()?
    } else {
        String::from_utf8(bytes).ok()?
    };
    Some(
        text.trim_matches('\0')
            .trim_start_matches('\u{feff}')
            .to_string(),
    )
}
fn attr<'a, 'input>(node: roxmltree::Node<'a, 'input>, name: &str) -> Option<&'a str> {
    node.attributes()
        .find(|a| a.name() == name)
        .map(|a| a.value())
}
fn xml_grid(source: &str) -> Option<Grid> {
    let doc = roxmltree::Document::parse(source).ok()?;
    let table = doc
        .descendants()
        .find(|n| n.is_element() && n.tag_name().name() == "Table")?;
    let mut styles = std::collections::BTreeMap::new();
    for style in doc
        .descendants()
        .filter(|n| n.is_element() && n.tag_name().name() == "Style")
    {
        let mut css = String::new();
        for node in style.children().filter(|n| n.is_element()) {
            let color = attr(node, "Color").filter(|s| {
                s.len() == 7 && s.starts_with('#') && s[1..].bytes().all(|b| b.is_ascii_hexdigit())
            });
            if node.tag_name().name() == "Font" {
                if let Some(color) = color {
                    css.push_str(&format!("color:{color};"));
                }
                if attr(node, "Bold") == Some("1") {
                    css.push_str("font-weight:bold;");
                }
                if attr(node, "Italic") == Some("1") {
                    css.push_str("font-style:italic;");
                }
            }
            if node.tag_name().name() == "Interior" {
                if let Some(color) = color {
                    css.push_str(&format!("background-color:{color};"));
                }
            }
        }
        styles.insert(attr(style, "ID").unwrap_or("").to_string(), css);
    }
    let mut rows = Vec::new();
    let mut count = 0;
    for row in table
        .children()
        .filter(|n| n.is_element() && n.tag_name().name() == "Row")
    {
        let at = attr(row, "Index")
            .and_then(|s| s.parse::<usize>().ok())
            .unwrap_or(rows.len() + 1);
        if at == 0 || at > 4096 {
            return None;
        }
        while rows.len() + 1 < at {
            rows.push(Vec::new());
        }
        let mut cells = Vec::new();
        for node in row
            .children()
            .filter(|n| n.is_element() && n.tag_name().name() == "Cell")
        {
            let at = attr(node, "Index")
                .and_then(|s| s.parse::<usize>().ok())
                .unwrap_or(cells.len() + 1);
            if at == 0 || at > 4096 {
                return None;
            }
            while cells.len() + 1 < at {
                cells.push(Cell::default());
                count += 1;
                if count > 20000 {
                    return None;
                }
            }
            let data = node
                .children()
                .find(|n| n.is_element() && n.tag_name().name() == "Data");
            let text = data
                .map(|n| {
                    n.descendants()
                        .filter_map(|n| n.text().filter(|_| n.is_text()))
                        .collect()
                })
                .unwrap_or_default();
            let kind = data
                .and_then(|n| attr(n, "Type"))
                .unwrap_or("String")
                .to_string();
            let span = attr(node, "MergeAcross")
                .and_then(|s| s.parse::<usize>().ok())
                .unwrap_or(0)
                + 1;
            if span > 4096 || cells.len() + span > 4096 {
                return None;
            }
            cells.push(Cell {
                text,
                kind,
                formula: attr(node, "Formula").map(str::to_string),
                style: styles
                    .get(attr(node, "StyleID").unwrap_or(""))
                    .cloned()
                    .unwrap_or_default(),
                span,
            });
            for _ in 1..span {
                cells.push(Cell::default());
            }
            count += span;
            if count > 20000 {
                return None;
            }
        }
        rows.push(cells);
    }
    (!rows.is_empty()).then_some(rows)
}
fn grid(data: &Value) -> Option<Grid> {
    if let Some(raw) = data["formats_base64"]["XML Spreadsheet"].as_str() {
        return xml_grid(&decoded(raw)?);
    }
    if let Some(raw) = data["formats_base64"]["HTML Format"].as_str() {
        let source = decoded(raw)?;
        let html = scraper::Html::parse_document(&source);
        let table = html
            .select(&scraper::Selector::parse("table").ok()?)
            .next()?;
        let mut rows = Vec::new();
        let mut count = 0;
        for row in table.select(&scraper::Selector::parse("tr").ok()?) {
            let mut cells = Vec::new();
            for cell in row.select(&scraper::Selector::parse("td,th").ok()?) {
                let number = cell
                    .value()
                    .attr("x:num")
                    .filter(|s| s.parse::<f64>().is_ok_and(f64::is_finite));
                let text = number
                    .map(str::to_string)
                    .unwrap_or_else(|| cell.text().collect::<String>());
                let kind = if number.is_some() { "Number" } else { "String" }.into();
                cells.push(Cell {
                    text,
                    kind,
                    span: 1,
                    ..Cell::default()
                });
                count += 1;
                if cells.len() > 4096 || count > 20000 {
                    return None;
                }
            }
            rows.push(cells);
            if rows.len() > 4096 {
                return None;
            }
        }
        return (!rows.is_empty()).then_some(rows);
    }
    let unicode = data["formats_base64"]["CF_UNICODETEXT"]
        .as_str()
        .and_then(|s| STANDARD.decode(s).ok())
        .and_then(|bytes| {
            String::from_utf16(
                &bytes
                    .chunks_exact(2)
                    .map(|b| u16::from_le_bytes([b[0], b[1]]))
                    .collect::<Vec<_>>(),
            )
            .ok()
        });
    let text = unicode
        .as_deref()
        .map(|s| s.trim_end_matches('\0'))
        .or_else(|| data["content"].as_str())?;
    if !text.contains('\t') {
        return None;
    }
    let mut reader = csv::ReaderBuilder::new()
        .delimiter(b'\t')
        .has_headers(false)
        .flexible(true)
        .from_reader(text.as_bytes());
    let mut rows = Vec::new();
    let mut count = 0;
    for row in reader.records() {
        let row = row.ok()?;
        count += row.len();
        if row.len() > 4096 || count > 20000 || rows.len() >= 4096 {
            return None;
        }
        rows.push(
            row.iter()
                .map(|s| Cell {
                    text: s.into(),
                    kind: "String".into(),
                    span: 1,
                    ..Cell::default()
                })
                .collect(),
        );
    }
    (!rows.is_empty()).then_some(rows)
}
fn xml(rows: &Grid, formulas: bool) -> String {
    let mut out=String::from("<?xml version=\"1.0\"?><Workbook xmlns=\"urn:schemas-microsoft-com:office:spreadsheet\" xmlns:ss=\"urn:schemas-microsoft-com:office:spreadsheet\"><Worksheet ss:Name=\"Clipboard\"><Table>");
    for row in rows {
        out.push_str("<Row>");
        for cell in row {
            out.push_str("<Cell");
            if formulas {
                if let Some(formula) = &cell.formula {
                    out.push_str(&format!(" ss:Formula=\"{}\"", esc(formula)));
                }
            }
            let kind = if ["Number", "Boolean", "DateTime", "Error"].contains(&cell.kind.as_str()) {
                cell.kind.as_str()
            } else {
                "String"
            };
            out.push_str(&format!(
                "><Data ss:Type=\"{kind}\">{}</Data></Cell>",
                esc(&cell.text)
            ));
        }
        out.push_str("</Row>");
    }
    out.push_str("</Table></Worksheet></Workbook>");
    out
}
fn tsv(rows: &Grid) -> String {
    let mut writer = csv::WriterBuilder::new()
        .delimiter(b'\t')
        .terminator(csv::Terminator::CRLF)
        .from_writer(Vec::new());
    for row in rows {
        let _ = writer.write_record(row.iter().map(|c| c.text.as_str()));
    }
    String::from_utf8(writer.into_inner().unwrap_or_default()).unwrap_or_default()
}
fn column(mut n: usize) -> String {
    let mut result = String::new();
    loop {
        result.insert(0, (b'A' + (n % 26) as u8) as char);
        if n < 26 {
            break;
        }
        n = n / 26 - 1;
    }
    result
}
fn run(request: &Value, settings: &Value) -> Value {
    if request["api_version"] != 2
        || request["type"] != "extension"
        || request["event"] != "command"
        || request["payload"]["kind"] != "clipboard"
    {
        return protocol::declined();
    }
    let data = &request["payload"]["data"];
    let command = request["command"].as_str().unwrap_or("");
    let command = if command == "paste-default" {
        settings["default_paste"]
            .as_str()
            .unwrap_or("paste-original")
    } else {
        command
    };
    if command == "paste-original" {
        return protocol::success("original", Value::Null);
    }
    if command != "render" {
        for name in ["XML Spreadsheet", "HTML Format", "CF_UNICODETEXT"] {
            if data["formats_base64"][name].is_string() {
                break;
            }
            if data["format_names"]
                .as_array()
                .is_some_and(|names| names.iter().any(|n| n == name))
            {
                return protocol::success(
                    "error",
                    json!(
                        if data["language"].as_str().unwrap_or("").starts_with("zh") {
                            "数据超过插件传输限制，请使用原格式粘贴。"
                        } else {
                            "Data exceeds plugin transfer limits. Use original-format paste."
                        }
                    ),
                );
            }
        }
    }
    let Some(mut rows) = grid(data) else {
        return protocol::declined();
    };
    if command == "render" {
        let limit = settings["preview_rows"]
            .as_u64()
            .unwrap_or(30)
            .clamp(1, 200) as usize;
        let columns = settings["preview_columns"]
            .as_u64()
            .unwrap_or(12)
            .clamp(1, 50) as usize;
        let width = rows.iter().map(Vec::len).max().unwrap_or(0).min(columns);
        let border = if data["appearance"] == "dark" {
            "#56616A"
        } else {
            "#C5CED5"
        };
        let mut html=format!("<table border=\"1\" cellspacing=\"0\" cellpadding=\"4\" style=\"border-color:{border}\"><tr><th></th>");
        for c in 0..width {
            html.push_str(&format!("<th>{}</th>", column(c)));
        }
        html.push_str("</tr>");
        let mut remaining = 200000;
        for (index, row) in rows.iter().take(limit).enumerate() {
            html.push_str(&format!("<tr><th>{}</th>", index + 1));
            let mut c = 0;
            while c < row.len().min(columns) {
                let cell = &row[c];
                let span = cell.span.max(1).min(columns - c);
                let text = if settings["show_formulas"].as_bool().unwrap_or(false) {
                    cell.formula.as_deref().unwrap_or(&cell.text)
                } else {
                    &cell.text
                };
                let shown: String = text.chars().take(remaining.min(1000)).collect();
                remaining -= shown.chars().count();
                html.push_str(&format!(
                    "<td colspan=\"{span}\" style=\"{}\" title=\"{}\">{}{}</td>",
                    esc(&cell.style),
                    esc(cell.formula.as_deref().unwrap_or("")),
                    esc(&shown).replace('\n', "<br>"),
                    if shown.len() < text.len() { "…" } else { "" }
                ));
                c += span;
            }
            html.push_str("</tr>");
        }
        html.push_str("</table>");
        let total_columns = rows.iter().map(Vec::len).max().unwrap_or(0);
        html.push_str(&format!(
            "<p>{}/{} × {}/{}</p>",
            rows.len().min(limit),
            rows.len(),
            width,
            total_columns
        ));
        return protocol::success("preview", json!({"kind":"html","content":html}));
    }
    if !["paste-values", "paste-formulas", "transpose-values"].contains(&command) {
        return protocol::declined();
    }
    if command == "paste-formulas" && !rows.iter().flatten().any(|c| c.formula.is_some()) {
        return protocol::success(
            "error",
            json!(
                if data["language"].as_str().unwrap_or("").starts_with("zh") {
                    "该条目没有保存公式，请使用数值或原格式粘贴。"
                } else {
                    "No formulas were stored. Use values or original-format paste."
                }
            ),
        );
    }
    if command == "transpose-values" {
        let width = rows.iter().map(Vec::len).max().unwrap_or(0);
        if rows.len().saturating_mul(width) > 20000 {
            return protocol::success(
                "error",
                json!("The transposed range exceeds the cell limit."),
            );
        }
        rows = (0..width)
            .map(|c| {
                rows.iter()
                    .map(|r| r.get(c).cloned().unwrap_or_default())
                    .collect()
            })
            .collect();
    }
    let mut payload = xml(&rows, command == "paste-formulas").into_bytes();
    payload.push(0);
    protocol::success(
        "clipboard",
        json!({"text":tsv(&rows),"formats_base64":{"XML Spreadsheet":STANDARD.encode(payload)}}),
    )
}
fn main() -> io::Result<()> {
    let mut bytes = Vec::new();
    io::stdin()
        .take(8 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)?;
    let request = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    serde_json::to_writer(io::stdout().lock(), &run(&request, &config()))?;
    io::stdout().flush()
}
#[cfg(test)]
mod tests {
    use super::*;
    const SAMPLE: &str = r#"<Workbook xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet><Table><Row><Cell><Data ss:Type="Number">20</Data></Cell><Cell ss:Formula="=RC[-1]*2"><Data ss:Type="Number">40</Data></Cell></Row></Table></Worksheet></Workbook>"#;
    fn input(command: &str) -> Value {
        protocol::test_command(
            command,
            "clipboard",
            json!({"content_type":"text","content":"20\t40","formats_base64":{"XML Spreadsheet":STANDARD.encode(SAMPLE)}}),
        )
    }
    #[test]
    fn preview_and_formula_round_trip() {
        let result = run(&input("render"), &json!({"show_formulas":true}));
        assert!(result["payload"]["data"]["content"]
            .as_str()
            .unwrap()
            .contains("=RC[-1]*2"));
        let result = run(&input("paste-formulas"), &json!({}));
        let xml = decoded(
            result["payload"]["data"]["formats_base64"]["XML Spreadsheet"]
                .as_str()
                .unwrap(),
        )
        .unwrap();
        assert!(xml.contains("ss:Formula"));
        assert!(xml_grid(&xml).is_some());
    }
    #[test]
    fn values_remove_formulas_and_transpose_is_rectangular() {
        let result = run(&input("paste-values"), &json!({}));
        let xml = decoded(
            result["payload"]["data"]["formats_base64"]["XML Spreadsheet"]
                .as_str()
                .unwrap(),
        )
        .unwrap();
        assert!(!xml.contains("ss:Formula"));
        let result = run(&input("transpose-values"), &json!({}));
        assert_eq!(result["payload"]["data"]["text"], "20\r\n40\r\n");
    }
    #[test]
    fn tsv_quotes_and_escaping_are_safe() {
        let rows = grid(&json!({"content":"\"a\tb\"\t\"<img>\""})).unwrap();
        assert_eq!(rows[0][0].text, "a\tb");
        assert!(xml(&rows, false).contains("&lt;img&gt;"));
        assert!(xml_grid("<!DOCTYPE x [<!ENTITY a SYSTEM 'file:///secret'>]><Table/>").is_none());
    }
}
