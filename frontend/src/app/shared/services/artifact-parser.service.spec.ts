import { ArtifactParserService } from './artifact-parser.service';

describe('ArtifactParserService', () => {
  let service: ArtifactParserService;

  beforeEach(() => {
    service = new ArtifactParserService();
  });

  it('returns prose unchanged when no artifacts', () => {
    const result = service.parse('Hello world');
    expect(result.prose).toBe('Hello world');
    expect(result.artifacts).toEqual([]);
  });

  it('extracts a code artifact', () => {
    const input =
      'Here is code:\n<artifact type="code" language="python" title="Test">print("hi")</artifact>\nDone.';
    const result = service.parse(input);
    expect(result.artifacts.length).toBe(1);
    expect(result.artifacts[0].type).toBe('code');
    expect(result.artifacts[0].language).toBe('python');
    expect(result.artifacts[0].title).toBe('Test');
    expect(result.artifacts[0].content).toBe('print("hi")');
    expect(result.prose).toContain('Here is code:');
    expect(result.prose).toContain('[artifact:');
    expect(result.prose).toContain('Done.');
  });

  it('extracts a chart artifact with JSON', () => {
    const json = '{"chartType":"bar","data":{"labels":["A"],"datasets":[{"data":[1]}]},"options":{}}';
    const input = `<artifact type="chart" title="Stats">${json}</artifact>`;
    const result = service.parse(input);
    expect(result.artifacts[0].type).toBe('chart');
    expect(result.artifacts[0].content).toBe(json);
  });

  it('extracts multiple artifacts', () => {
    const input =
      '<artifact type="code" language="js" title="A">a()</artifact> and <artifact type="html" title="B"><p>hi</p></artifact>';
    const result = service.parse(input);
    expect(result.artifacts.length).toBe(2);
  });

  it('strips markdown code block wrapping around artifact tag', () => {
    const input = '```\n<artifact type="code" language="python" title="X">code()</artifact>\n```';
    const result = service.parse(input);
    expect(result.artifacts.length).toBe(1);
    expect(result.artifacts[0].content).toBe('code()');
  });

  it('auto-promotes large code blocks without artifact tags', () => {
    const lines = Array.from({ length: 20 }, (_, i) => `line ${i}`).join('\n');
    const input = '```python\n' + lines + '\n```';
    const result = service.parse(input);
    expect(result.artifacts.length).toBe(1);
    expect(result.artifacts[0].type).toBe('code');
    expect(result.artifacts[0].language).toBe('python');
  });

  it('does not auto-promote small code blocks', () => {
    const input = '```python\nprint("hi")\n```';
    const result = service.parse(input);
    expect(result.artifacts.length).toBe(0);
    expect(result.prose).toContain('```python');
  });

  it('defaults missing type to markdown', () => {
    const input = '<artifact title="Note">some text</artifact>';
    const result = service.parse(input);
    expect(result.artifacts[0].type).toBe('markdown');
  });

  it('generates title when missing', () => {
    const input = '<artifact type="code" language="python">x = 1</artifact>';
    const result = service.parse(input);
    expect(result.artifacts[0].title).toBeTruthy();
  });
});
