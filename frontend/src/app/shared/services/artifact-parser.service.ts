import { Injectable } from '@angular/core';
import { Artifact, ArtifactType, ParsedContent } from '../../core/models/llm.model';

const AUTO_PROMOTE_LINE_THRESHOLD = 15;

const DEFAULT_TITLES: Record<string, string> = {
  code: 'Code Snippet',
  markdown: 'Document',
  html: 'HTML Content',
  mermaid: 'Diagram',
  svg: 'SVG Graphic',
  chart: 'Chart',
};

const VALID_TYPES = new Set<ArtifactType>(['code', 'markdown', 'html', 'mermaid', 'svg', 'chart']);

@Injectable({ providedIn: 'root' })
export class ArtifactParserService {
  parse(text: string): ParsedContent {
    // Step 1: Strip markdown code block wrapping around artifact tags
    let cleaned = text.replace(/```[^\n]*\n(<artifact[\s\S]*?<\/artifact>)\n```/g, '$1');

    const artifacts: Artifact[] = [];

    // Step 2: Extract <artifact> tags — splice by index in reverse to keep positions stable
    const attrPattern = /<artifact\s*([^>]*)>([\s\S]*?)<\/artifact>/g;
    const tagMatches = Array.from(cleaned.matchAll(attrPattern));

    // Build replacements (index-based) then apply in reverse
    const replacements: { start: number; end: number; text: string }[] = [];
    for (const match of tagMatches) {
      const attrsStr = match[1];
      const content = match[2];
      const start = match.index!;
      const end = start + match[0].length;

      const type = (this._extractAttr(attrsStr, 'type') as ArtifactType) || 'markdown';

      // Markdown artifacts are inlined as rendered prose (not shown in an artifact card).
      // Unknown/unsupported types are also inlined to avoid broken cards.
      if (type === 'markdown' || !VALID_TYPES.has(type)) {
        replacements.push({ start, end, text: content.trim() });
        continue;
      }

      const title = this._extractAttr(attrsStr, 'title') || DEFAULT_TITLES[type] || 'Artifact';
      const language = this._extractAttr(attrsStr, 'language') || undefined;

      const artifact: Artifact = {
        id: crypto.randomUUID(),
        type,
        title,
        language,
        content: content.trim(),
      };
      artifacts.push(artifact);
      replacements.push({ start, end, text: `[artifact:${artifact.id}]` });
    }

    let prose = this._applyReplacements(cleaned, replacements);

    // Step 3: Auto-promote large code blocks (only if no artifacts were found via tags)
    if (artifacts.length === 0) {
      const codePattern = /```([^\n`]*)?\n([\s\S]*?)```/g;
      const codeMatches = Array.from(prose.matchAll(codePattern));
      const codeReplacements: { start: number; end: number; text: string }[] = [];
      for (const codeMatch of codeMatches) {
        const lang = codeMatch[1] || undefined;
        const code = codeMatch[2];
        const lineCount = code.split('\n').length;
        if (lineCount >= AUTO_PROMOTE_LINE_THRESHOLD) {
          const artifact: Artifact = {
            id: crypto.randomUUID(),
            type: 'code',
            title: DEFAULT_TITLES['code'],
            language: lang,
            content: code.trim(),
          };
          artifacts.push(artifact);
          codeReplacements.push({
            start: codeMatch.index!,
            end: codeMatch.index! + codeMatch[0].length,
            text: `[artifact:${artifact.id}]`,
          });
        }
      }
      prose = this._applyReplacements(prose, codeReplacements);
    }

    return { prose: prose.trim(), artifacts };
  }

  /**
   * Detect if text contains an opening <artifact tag (for streaming).
   * Returns the parsed attributes if found, null otherwise.
   */
  detectOpeningTag(
    text: string,
  ): { type: ArtifactType; title: string; language?: string; startIndex: number; endIndex: number } | null {
    // Require type= attribute to avoid false positives when LLM mentions <artifact in prose/code
    const openPattern = /<artifact\s+((?=[^>]*type=)[^>]*)>/;
    const openMatch = openPattern.exec(text);
    if (!openMatch) return null;
    const attrs = openMatch[1];
    const type = (this._extractAttr(attrs, 'type') as ArtifactType) || 'markdown';
    // Markdown artifacts are inlined as prose — don't buffer them during streaming
    if (type === 'markdown' || !VALID_TYPES.has(type)) return null;
    const title = this._extractAttr(attrs, 'title') || DEFAULT_TITLES[type] || 'Artifact';
    const language = this._extractAttr(attrs, 'language') || undefined;
    return {
      type,
      title,
      language,
      startIndex: openMatch.index,
      endIndex: openMatch.index + openMatch[0].length,
    };
  }

  /** Check if text contains a closing </artifact> tag. */
  hasClosingTag(text: string): boolean {
    return text.includes('</artifact>');
  }

  /** Apply index-based replacements in reverse order so positions stay stable. */
  private _applyReplacements(text: string, replacements: { start: number; end: number; text: string }[]): string {
    for (let i = replacements.length - 1; i >= 0; i--) {
      const r = replacements[i];
      text = text.slice(0, r.start) + r.text + text.slice(r.end);
    }
    return text;
  }

  private _extractAttr(attrsStr: string, name: string): string | null {
    const re = new RegExp(`${name}="([^"]*)"`, 'i');
    const m = re.exec(attrsStr);
    return m ? m[1] : null;
  }
}
