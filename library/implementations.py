class SummarizerTool(BaseTool):
    name = "Quick Summarizer"
    description = "Trims long text into a punchy summary."
    version = "1.1"

    def validate(self):
        text = self.user_input.get("raw_text", "")
        if len(text) < 10:
            self.errors["raw_text"] = "Text is too short to summarize."

    def process(self):
        # Implementation of Tactic 3: execution pipeline
        text = self.user_input.get("raw_text", "")
        summary = text[:100] + "..." # Simplified logic
        
        # Returns structured data for Tactic 2 (Storage)
        return {
            "summary": summary,
            "word_count": len(text.split()),
        }