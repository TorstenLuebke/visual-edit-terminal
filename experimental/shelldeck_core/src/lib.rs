//! Experimental stable logical-line storage. No PTY/VT parser or GUI integration.
//! Lines have identities independent of viewport dimensions. Reflow produces
//! display segments without rewriting stored logical text.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Anchor {
    pub line_id: u64,
    pub character_offset: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LogicalLine {
    pub id: u64,
    pub text: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DisplaySegment {
    pub line_id: u64,
    pub first_character: usize,
    pub text: String,
}

#[derive(Default)]
pub struct LogicalBuffer {
    next_id: u64,
    lines: Vec<LogicalLine>,
}

impl LogicalBuffer {
    pub fn new() -> Self { Self::default() }

    pub fn push(&mut self, value: impl Into<String>) -> u64 {
        let id = self.next_id;
        self.next_id = self.next_id.checked_add(1).expect("line id overflow");
        self.lines.push(LogicalLine { id, text: value.into() });
        id
    }

    pub fn line(&self, id: u64) -> Option<&LogicalLine> {
        self.lines.iter().find(|line| line.id == id)
    }

    pub fn valid_anchor(&self, anchor: Anchor) -> bool {
        self.line(anchor.line_id).is_some_and(|line| {
            anchor.character_offset <= line.text.chars().count()
        })
    }

    pub fn evict_oldest(&mut self, max_lines: usize) {
        if self.lines.len() > max_lines {
            self.lines.drain(..self.lines.len() - max_lines);
        }
    }

    /// Extracts an inclusive-start, exclusive-end logical selection.
    /// Character offsets use Unicode scalar values, not bytes or display cells.
    /// Missing/evicted anchors, reversed ranges and nonexisting endpoints fail.
    pub fn selected_text(&self, start: Anchor, end: Anchor) -> Option<String> {
        let start_index = self.lines.iter().position(|line| line.id == start.line_id)?;
        let end_index = self.lines.iter().position(|line| line.id == end.line_id)?;
        if start_index > end_index ||
            (start_index == end_index && start.character_offset > end.character_offset) ||
            !self.valid_anchor(start) || !self.valid_anchor(end) { return None; }
        let mut parts = Vec::new();
        for (index, line) in self.lines[start_index..=end_index].iter().enumerate() {
            let begin = if index == 0 { start.character_offset } else { 0 };
            let stop = if start_index + index == end_index {
                end.character_offset
            } else { line.text.chars().count() };
            parts.push(line.text.chars().skip(begin).take(stop - begin).collect::<String>());
        }
        Some(parts.join("\n"))
    }

    /// Character-count prototype: real terminal reflow also needs Unicode cell
    /// widths, wrap flags, attributes and explicit-vs-soft line breaks.
    pub fn layout(&self, columns: usize) -> Result<Vec<DisplaySegment>, &'static str> {
        if columns == 0 { return Err("columns must be positive"); }
        let mut output = Vec::new();
        for line in &self.lines {
            let chars: Vec<char> = line.text.chars().collect();
            if chars.is_empty() {
                output.push(DisplaySegment { line_id: line.id,
                    first_character: 0, text: String::new() });
            } else {
                for (index, segment) in chars.chunks(columns).enumerate() {
                    output.push(DisplaySegment { line_id: line.id,
                        first_character: index * columns,
                        text: segment.iter().collect() });
                }
            }
        }
        Ok(output)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shrink_and_grow_never_change_logical_data() {
        let mut lines = LogicalBuffer::new();
        let id = lines.push("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789".repeat(2));
        let expected = lines.line(id).unwrap().text.clone();
        let short = lines.layout(28).unwrap();
        assert!(short.iter().filter(|s| s.line_id == id).count() > 1);
        assert_eq!(short.iter().map(|s| s.text.as_str()).collect::<String>(), expected);
        lines.layout(100).unwrap();
        assert_eq!(lines.line(id).unwrap().text, expected);
    }

    #[test]
    fn anchors_survive_viewport_changes_and_invalidate_on_eviction() {
        let mut lines = LogicalBuffer::new();
        let id = lines.push("abc def");
        let anchor = Anchor { line_id: id, character_offset: 4 };
        assert!(lines.valid_anchor(anchor));
        lines.layout(2).unwrap();
        lines.layout(80).unwrap();
        assert!(lines.valid_anchor(anchor));
        lines.push("next");
        lines.evict_oldest(1);
        assert!(!lines.valid_anchor(anchor));
    }

    #[test]
    fn selection_is_stable_across_layouts() {
        let mut lines = LogicalBuffer::new();
        let a = lines.push("ä🐧alpha");
        let b = lines.push("beta");
        let start = Anchor { line_id: a, character_offset: 1 };
        let end = Anchor { line_id: b, character_offset: 2 };
        assert_eq!(lines.selected_text(start, end).as_deref(), Some("🐧alpha\nbe"));
        lines.layout(2).unwrap();
        lines.layout(120).unwrap();
        assert_eq!(lines.selected_text(start, end).as_deref(), Some("🐧alpha\nbe"));
        lines.evict_oldest(1);
        assert_eq!(lines.selected_text(start, end), None);
    }

    #[test]
    fn reversed_and_invalid_selections_fail() {
        let mut lines = LogicalBuffer::new();
        let a = lines.push("hello");
        assert_eq!(lines.selected_text(Anchor { line_id: a, character_offset: 4 },
            Anchor { line_id: a, character_offset: 2 }), None);
        assert_eq!(lines.selected_text(Anchor { line_id: a, character_offset: 0 },
            Anchor { line_id: a, character_offset: 99 }), None);
    }

    #[test]
    fn rejects_zero_columns() {
        assert!(LogicalBuffer::new().layout(0).is_err());
    }

    #[test]
    fn unicode_offsets_are_characters_not_bytes() {
        let mut lines = LogicalBuffer::new();
        let id = lines.push("ä🐧x");
        assert!(lines.valid_anchor(Anchor { line_id: id, character_offset: 3 }));
        assert!(!lines.valid_anchor(Anchor { line_id: id, character_offset: 4 }));
        assert_eq!(lines.layout(2).unwrap()[0].text, "ä🐧");
    }
}
