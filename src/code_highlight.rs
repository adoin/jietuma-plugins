mod protocol;
use serde_json::{json, Value};
use std::io::{self, Read, Write};
use syntect::{
    easy::HighlightLines,
    highlighting::ThemeSet,
    parsing::{SyntaxDefinition, SyntaxSet},
    util::LinesWithEndings,
};

fn escape(s: &str) -> String {
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
fn extension(language: &str) -> &str {
    match language {
        "python" => "py",
        "javascript" => "js",
        "typescript" | "tsx" => "ts",
        "rust" => "rs",
        "csharp" => "cs",
        "shell" => "sh",
        "powershell" => "ps1",
        "cpp" => "cpp",
        "markdown" => "md",
        other => other,
    }
}
fn syntaxes() -> SyntaxSet {
    let mut builder = SyntaxSet::load_defaults_newlines().into_builder();
    for yaml in [
        r#"%YAML 1.2
---
name: TypeScript
file_extensions: [ts, tsx]
scope: source.ts
contexts:
  main:
    - match: '\b(interface|type|declare|namespace|implements|readonly|keyof|infer|abstract|as|satisfies)\b'
      scope: keyword.declaration.ts
    - match: '\b(string|number|boolean|unknown|never|any|void)\b'
      scope: storage.type.ts
    - include: scope:source.js
"#,
        r#"%YAML 1.2
---
name: PowerShell
file_extensions: [ps1, psm1, psd1]
scope: source.powershell
contexts:
  main:
    - match: '#.*$'
      scope: comment.line.powershell
    - match: '\b(?i:function|param|if|else|elseif|foreach|for|while|return|try|catch|finally|throw|class|using|switch)\b'
      scope: keyword.control.powershell
    - match: '\$[A-Za-z_][A-Za-z0-9_:]*'
      scope: variable.other.powershell
    - match: '\b[A-Za-z]+-[A-Za-z0-9-]+\b'
      scope: support.function.powershell
    - match: '"[^"\n]*"'
      scope: string.quoted.double.powershell
    - match: "'[^'\\n]*'"
      scope: string.quoted.single.powershell
    - match: '\b\d+(\.\d+)?\b'
      scope: constant.numeric.powershell
"#,
        r#"%YAML 1.2
---
name: TOML
file_extensions: [toml]
scope: source.toml
contexts:
  main:
    - match: '#.*$'
      scope: comment.line.toml
    - match: '\[.*\]'
      scope: entity.name.section.toml
    - match: '[A-Za-z_][A-Za-z0-9_-]*(?=\s*=)'
      scope: variable.other.toml
    - match: '"[^"\n]*"'
      scope: string.quoted.double.toml
    - match: '\b(true|false)\b'
      scope: constant.language.toml
    - match: '\b\d+(\.\d+)?\b'
      scope: constant.numeric.toml
"#,
    ] {
        if let Ok(syntax) = SyntaxDefinition::load_from_str(yaml, true, None) {
            builder.add(syntax);
        }
    }
    builder.build()
}
fn run(request: &Value, settings: &Value) -> Value {
    let Some(data) = protocol::command(request, "render", "clipboard") else {
        return protocol::declined();
    };
    let mut language = data["metadata"]["language"]
        .as_str()
        .unwrap_or("plain")
        .to_string();
    let mut text = data["content"].as_str().unwrap_or("").to_string();
    if data["content_type"] == "file" {
        let Some(path) = data["paths"]
            .as_array()
            .filter(|a| a.len() == 1)
            .and_then(|a| a[0].as_str())
        else {
            return protocol::declined();
        };
        if path.starts_with("\\\\") || path.starts_with("//") {
            return protocol::declined();
        }
        language = std::path::Path::new(path)
            .extension()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .to_lowercase();
        if ![
            "rs", "py", "js", "ts", "jsx", "tsx", "json", "cpp", "c", "h", "cs", "sql", "xml",
            "html", "css", "yaml", "yml", "toml", "sh", "ps1", "java", "go", "rb", "php", "md",
        ]
        .contains(&language.as_str())
        {
            return protocol::declined();
        }
        let Ok(metadata) = std::fs::metadata(path) else {
            return protocol::declined();
        };
        if metadata.len() > 200000 {
            return protocol::declined();
        }
        let Ok(source) = std::fs::read_to_string(path) else {
            return protocol::declined();
        };
        text = source;
    }
    if language == "plain" || language.is_empty() {
        return protocol::declined();
    }
    let syntaxes = syntaxes();
    let syntax = syntaxes
        .find_syntax_by_extension(extension(&language))
        .unwrap_or_else(|| syntaxes.find_syntax_plain_text());
    let themes = ThemeSet::load_defaults();
    let selected = settings["theme"].as_str().unwrap_or("auto");
    let dark = selected == "dark" || (selected == "auto" && data["appearance"] == "dark");
    let theme = &themes.themes[if dark {
        "base16-ocean.dark"
    } else {
        "InspiredGitHub"
    }];
    let mut highlighter = HighlightLines::new(syntax, theme);
    let limit = settings["max_lines"].as_u64().unwrap_or(200).clamp(10, 500) as usize;
    let chars = settings["max_chars"]
        .as_u64()
        .unwrap_or(50000)
        .clamp(500, 200000) as usize;
    let source: String = text.chars().take(chars).collect();
    let numbered = settings["line_numbers"].as_bool().unwrap_or(true);
    let background = theme
        .settings
        .background
        .unwrap_or(syntect::highlighting::Color {
            r: 255,
            g: 255,
            b: 255,
            a: 255,
        });
    let foreground = theme
        .settings
        .foreground
        .unwrap_or(syntect::highlighting::Color {
            r: 0,
            g: 0,
            b: 0,
            a: 255,
        });
    let mut html=format!("<table cellspacing=\"0\" cellpadding=\"2\" style=\"color:#{:02x}{:02x}{:02x};background-color:{}\">",foreground.r,foreground.g,foreground.b,if selected=="auto"{"transparent".into()}else{format!("#{:02x}{:02x}{:02x}",background.r,background.g,background.b)});
    for (index, line) in LinesWithEndings::from(&source).take(limit).enumerate() {
        let Ok(ranges) = highlighter.highlight_line(line, &syntaxes) else {
            return protocol::declined();
        };
        html.push_str("<tr>");
        if numbered {
            html.push_str(&format!(
                "<td style=\"color:{}\">{}</td>",
                if dark { "#9AA5B1" } else { "#68737D" },
                index + 1
            ));
        }
        html.push_str(
            "<td><pre style=\"margin:0;font-family:Consolas,monospace;white-space:pre\">",
        );
        if line.trim_end_matches(['\r', '\n']).is_empty() {
            html.push_str("&#8203;");
        }
        for (style, part) in ranges {
            html.push_str(&format!(
                "<span style=\"color:#{:02x}{:02x}{:02x}\">{}</span>",
                style.foreground.r,
                style.foreground.g,
                style.foreground.b,
                escape(part.trim_end_matches('\n'))
            ));
        }
        html.push_str("</pre></td></tr>");
    }
    html.push_str("</table>");
    if text.chars().count() > chars || source.lines().count() > limit {
        html.push_str("<p>…</p>");
    }
    protocol::success("preview", json!({"kind":"html","content":html}))
}
fn main() -> io::Result<()> {
    let mut input = Vec::new();
    io::stdin()
        .take(8 * 1024 * 1024 + 1)
        .read_to_end(&mut input)?;
    let value = serde_json::from_slice(&input).unwrap_or(Value::Null);
    serde_json::to_writer(io::stdout().lock(), &run(&value, &config()))?;
    io::stdout().flush()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ordinary_text_is_not_guessed_and_manual_language_is_honored() {
        let mut data =
            json!({"content_type":"text","content":"if this is ordinary prose","metadata":{}});
        assert_eq!(
            run(
                &protocol::test_command("render", "clipboard", data.clone()),
                &json!({})
            )["payload"]["kind"],
            "none"
        );
        data["content"] = json!("def answer():\n    return 42\n");
        data["metadata"] = json!({"language":"python"});
        let rendered = run(
            &protocol::test_command("render", "clipboard", data),
            &json!({}),
        );
        assert_eq!(rendered["payload"]["kind"], "preview");
        assert!(rendered["payload"]["data"]["content"]
            .as_str()
            .unwrap()
            .contains("color:#"));
    }
    #[test]
    fn html_is_escaped() {
        assert_eq!(escape("<img src=\"x\">"), "&lt;img src=&quot;x&quot;&gt;");
    }
    #[test]
    fn shipped_language_presets_have_grammars() {
        let set = syntaxes();
        for language in [
            "python",
            "javascript",
            "typescript",
            "json",
            "rust",
            "cpp",
            "csharp",
            "java",
            "go",
            "sql",
            "html",
            "xml",
            "css",
            "yaml",
            "toml",
            "shell",
            "powershell",
            "markdown",
        ] {
            assert!(
                set.find_syntax_by_extension(extension(language)).is_some(),
                "{language}"
            );
        }
    }
}
