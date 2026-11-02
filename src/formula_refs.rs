// Translate R1C1 references at the destination, retaining $ anchors and literals.
fn axis(chars: &[char], at: &mut usize, origin: i64) -> Option<(i64, bool)> {
    if chars.get(*at) == Some(&'[') {
        *at += 1;
        let start = *at;
        if matches!(chars.get(*at), Some('+' | '-')) {
            *at += 1;
        }
        while chars.get(*at).is_some_and(char::is_ascii_digit) {
            *at += 1;
        }
        let delta = chars[start..*at]
            .iter()
            .collect::<String>()
            .parse::<i64>()
            .ok()?;
        if chars.get(*at) != Some(&']') {
            return None;
        }
        *at += 1;
        Some((origin.checked_add(delta)?, false))
    } else {
        let start = *at;
        while chars.get(*at).is_some_and(char::is_ascii_digit) {
            *at += 1;
        }
        if start == *at {
            Some((origin, false))
        } else {
            Some((
                chars[start..*at].iter().collect::<String>().parse().ok()?,
                true,
            ))
        }
    }
}
fn word(c: char) -> bool {
    c.is_alphanumeric() || matches!(c, '_' | '.' | '$')
}
fn col(mut col: i64) -> String {
    let mut out = String::new();
    while col > 0 {
        col -= 1;
        out.insert(0, (b'A' + (col % 26) as u8) as char);
        col /= 26;
    }
    out
}
pub fn a1(formula: &str, row: usize, column: usize) -> String {
    let chars: Vec<char> = formula.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        if matches!(chars[i], '"' | '\'') {
            let quote = chars[i];
            out.push(quote);
            i += 1;
            while i < chars.len() {
                let current = chars[i];
                out.push(current);
                i += 1;
                if current == quote {
                    if chars.get(i) == Some(&quote) {
                        out.push(quote);
                        i += 1;
                    } else {
                        break;
                    }
                }
            }
            continue;
        }
        if chars[i] == '[' {
            let mut depth = 0;
            while i < chars.len() {
                let c = chars[i];
                i += 1;
                out.push(c);
                if c == '[' {
                    depth += 1;
                }
                if c == ']' {
                    depth -= 1;
                    if depth == 0 {
                        break;
                    }
                }
            }
            continue;
        }
        let kind = chars[i].to_ascii_uppercase();
        if matches!(kind, 'R' | 'C') && (i == 0 || !word(chars[i - 1])) {
            let mut end = i + 1;
            let first = axis(
                &chars,
                &mut end,
                if kind == 'R' {
                    row as i64
                } else {
                    column as i64
                },
            );
            if let Some(first) = first {
                let mut r = None;
                let mut c = None;
                if kind == 'R' {
                    r = Some(first);
                    if chars.get(end).is_some_and(|c| c.eq_ignore_ascii_case(&'C')) {
                        end += 1;
                        c = axis(&chars, &mut end, column as i64);
                        if c.is_none() {
                            out.push(chars[i]);
                            i += 1;
                            continue;
                        }
                    }
                } else {
                    c = Some(first);
                }
                if chars.get(end).is_none_or(|c| !word(*c) && *c != '!') {
                    let invalid = r.is_some_and(|v| v.0 < 1 || v.0 > 1_048_576)
                        || c.is_some_and(|v| v.0 < 1 || v.0 > 16_384);
                    if invalid {
                        out.push_str("#REF!");
                    } else {
                        let row_text =
                            r.map(|(n, abs)| format!("{}{n}", if abs { "$" } else { "" }));
                        let col_text =
                            c.map(|(n, abs)| format!("{}{}", if abs { "$" } else { "" }, col(n)));
                        let text = format!(
                            "{}{}",
                            col_text.as_deref().unwrap_or(""),
                            row_text.as_deref().unwrap_or("")
                        );
                        out.push_str(&text);
                        if (r.is_none() || c.is_none())
                            && chars.get(end) != Some(&':')
                            && (i == 0 || chars[i - 1] != ':')
                        {
                            out.push(':');
                            out.push_str(&text);
                        }
                    }
                    i = end;
                    continue;
                }
            }
        }
        out.push(chars[i]);
        i += 1;
    }
    out
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn relocates_both_axes_and_keeps_mixed_anchors() {
        assert_eq!(
            a1("=SUM(RC[-2]:RC[-1])+R2C2+R2C[-1]+RC2", 8, 4),
            "=SUM(B8:C8)+$B$2+C$2+$B8"
        );
        assert_eq!(a1("=SUM(RC[-2]:RC[-1])", 8, 7), "=SUM(E8:F8)");
        assert_eq!(a1("=RC[-1]", 1, 1), "=#REF!");
    }
    #[test]
    fn respects_literals_sheet_names_ranges_and_function_names() {
        assert_eq!(
            a1(
                "=IF(RC[-1]=\"RC[-2]\",'Sheet R1C1'!R2C3,RANK(RC[-1],C[-1]))",
                8,
                4
            ),
            "=IF(C8=\"RC[-2]\",'Sheet R1C1'!$C$2,RANK(C8,C:C))"
        );
        assert_eq!(
            a1("=SUM(R[-2]:R[-1])+SUM(C[-2]:C[-1])+Table1[RC]", 8, 4),
            "=SUM(6:7)+SUM(B:C)+Table1[RC]"
        );
    }
}
