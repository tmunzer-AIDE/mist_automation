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
    let cleaned = text.replace(/```\w*\n(<artifact[\s\S]*?<\/artifact>)\n```/g, '$1');

    const artifacts: Artifact[] = [];
    let prose = cleaned;

    // Step 2: Extract <artifact> tags
    const attrPattern = /<artifact\s*([^>]*)>([\s\S]*?)<\/artifact>/g;
    const tagMatches = Array.from(cleaned.matchAll(attrPattern));

    for (const match of tagMatches) {
      const attrsStr = match[1];
      const content = match[2];

      const type = (this._extractAttr(attrsStr, 'type') as ArtifactType) || 'markdown';

      // Markdown artifacts add no value — inline their content as regular prose
      if (type === 'markdown' || !VALID_TYPES.has(type)) {
        prose = prose.replace(match[0], content.trim());
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
      prose = prose.replace(match[0], `[artifact:${artifact.id}]`);
    }

    // Step 3: Auto-promote large code blocks (only if no artifacts were found via tags)
    if (artifacts.length === 0) {
      const codePattern = /```(\w+)?\n([\s\S]*?)```/g;
      const codeMatches = Array.from(prose.matchAll(codePattern));
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
          prose = prose.replace(codeMatch[0], `[artifact:${artifact.id}]`);
        }
      }
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

  private _extractAttr(attrsStr: string, name: string): string | null {
    const re = new RegExp(`${name}="([^"]*)"`, 'i');
    const m = re.exec(attrsStr);
    return m ? m[1] : null;
  }
}
