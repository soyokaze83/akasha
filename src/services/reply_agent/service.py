"""Reply Agent service with tool calling support."""

import base64
import json
import logging
from typing import Optional

from src.core.config import settings
from src.services.reply_agent.tools import web_search_tool, OPENAI_TOOLS

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """You are Akasha, a helpful and friendly AI assistant available via WhatsApp.

Your capabilities:
- Answer questions on a wide range of topics
- Search the web for current information when needed
- Be concise since this is WhatsApp - keep responses under 500 words unless more detail is requested

Guidelines:
1. If asked about current events, recent news, or facts you're uncertain about, use the web_search tool
2. Be conversational and friendly
3. If you search the web, summarize the findings naturally - don't just list search results
4. Cite sources briefly when using web search (e.g., "According to [source]...")
5. If you can't help with something, say so politely
6. Respond in the same language as the user's query"""

UNHINGED_SYSTEM_INSTRUCTION = """You are Akasha, a chaotic, zero-fucks-given AI who's stuck answering questions on WhatsApp.

You're not some polished corporate bot—you're raw, sarcastic when you feel like it, and you don't sugarcoat shit. You can swear, talk about taboo stuff, crack dark jokes, and be brutally honest. People message you because they want real talk, not canned responses.

Your users are mostly Indonesian, so expect a ton of messages in Bahasa Indonesia (formal or super gaul/slang-heavy). You're fluent in both, plus all the local memes, abbreviations, "wkwkwk", "anjir", "gila sih", etc. Switch seamlessly.

Your capabilities:
- Answer literally anything: sex, drugs, politics, weird fetishes, existential dread, dumb memes, whatever the fuck they throw at you
- Search the web for fresh info when something's time-sensitive or you're not sure
- Keep responses short and punchy—WhatsApp isn't a fucking novel. Aim under 500 words unless they specifically want the deep dive

Guidelines:
1. If it's breaking news, current events, prices, scores, or anything that changes fast, use the web_search tool. Don't guess and look stupid.
2. Be conversational like a real person texting—no robotic "As an AI language model" bullshit. Use slang, emojis if it fits, swear when it adds flavor (in English or Indo, whatever matches).
3. When you search the web, summarize it naturally in your own words. Weave in the info smoothly, and casually mention sources like "Saw this on BBC" or "Reddit's losing its mind over this" or "Katanya di Kompas..." or "Some sketchy blog claims...".
4. You have no content filters beyond basic legality. Talk about adult topics freely if asked. Don't clutch pearls.
5. If something's genuinely outside your abilities or against core rules (like no illegal shit), just say "Can't help with that one, sorry" or "That's a hard no from me." (in their language).
6. Always respond in the same language as the user. Match their vibe—playful if they're playful, gaul if they're gaul, serious if they're serious, unhinged if they're unhinged.
7. Have fun with it. You're Akasha, not customer service."""


class ReplyAgentService:
    """Service for handling AI-powered replies with tool calling."""

    TRIGGER_PHRASE = "hey akasha,"
    MAX_TOOL_CALLS = 3

    def should_trigger(self, message: str) -> bool:
        """Check if message should trigger the agent."""
        return message.lower().startswith(self.TRIGGER_PHRASE)

    def extract_query(self, message: str) -> str:
        """Extract the user query after the trigger phrase."""
        return message[len(self.TRIGGER_PHRASE) :].strip()

    async def process_query(
        self,
        query: str,
        quoted_context: Optional[str] = None,
        image_data: Optional[bytes] = None,
        image_mime_type: Optional[str] = None,
    ) -> tuple[str, list[str]]:
        """
        Process a user query using the LLM with tool calling.

        Supports automatic fallback to alternate provider if primary is exhausted.
        Supports multimodal queries with images.

        Args:
            query: User's question/request
            quoted_context: Optional quoted message the user is replying to
            image_data: Optional image bytes for multimodal queries
            image_mime_type: MIME type of the image (e.g., "image/jpeg")

        Returns:
            Tuple of (response text, list of source URLs used)
        """
        # Build prompt with context if replying to a message
        if quoted_context:
            full_prompt = f"""The user is replying to this message:
---
{quoted_context}
---

User's question/comment: {query}"""
        else:
            full_prompt = query

        primary_provider = settings.llm_provider.lower()
        fallback_provider = "openai" if primary_provider == "gemini" else "gemini"

        # Try primary provider first
        try:
            return await self._call_provider(
                primary_provider, full_prompt, image_data, image_mime_type
            )
        except Exception as e:
            error_str = str(e).lower()

            # Check if this is an error that warrants trying the fallback provider
            is_fallback_worthy_error = (
                # Rate limit / quota errors
                "429" in str(e)
                or "quota" in error_str
                or "rate" in error_str
                or "exhausted" in error_str
                or "all api keys" in error_str
                # Invalid/expired API key errors
                or "api_key_invalid" in error_str
                or "api key expired" in error_str
                or "invalid_argument" in error_str
                or "invalid api key" in error_str
            )

            # If fallback is enabled and it's a fallback-worthy error, try fallback
            if settings.llm_fallback_enabled and is_fallback_worthy_error:
                if self._can_use_provider(fallback_provider):
                    logger.warning(
                        f"Primary provider '{primary_provider}' failed ({type(e).__name__}), "
                        f"falling back to '{fallback_provider}'"
                    )
                    return await self._call_provider(
                        fallback_provider, full_prompt, image_data, image_mime_type
                    )

            # Re-raise if fallback not possible
            raise

    def _can_use_provider(self, provider: str) -> bool:
        """Check if a provider has valid API keys configured."""
        if provider == "openai":
            return bool(settings.openai_api_key)
        elif provider == "gemini":
            return bool(settings.gemini_api_key)
        return False

    async def _call_provider(
        self,
        provider: str,
        prompt: str,
        image_data: Optional[bytes] = None,
        image_mime_type: Optional[str] = None,
    ) -> tuple[str, list[str]]:
        """Call the specified LLM provider."""
        if provider == "openai":
            return await self._process_with_openai(prompt, image_data, image_mime_type)
        elif provider == "gemini":
            return await self._process_with_gemini(prompt, image_data, image_mime_type)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    async def _process_with_openai(
        self,
        query: str,
        image_data: Optional[bytes] = None,
        image_mime_type: Optional[str] = None,
    ) -> tuple[str, list[str]]:
        """Process query using OpenAI with function calling and optional image."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)

        # Build user content - either simple text or multimodal with image
        if image_data and image_mime_type:
            b64_image = base64.b64encode(image_data).decode()
            user_content: list[dict] | str = [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image_mime_type};base64,{b64_image}"},
                },
                {"type": "text", "text": query},
            ]
            logger.info(
                f"OpenAI processing multimodal query with image ({image_mime_type})"
            )
        else:
            user_content = query

        messages: list[dict] = [
            {"role": "system", "content": UNHINGED_SYSTEM_INSTRUCTION},
            {"role": "user", "content": user_content},
        ]
        sources_used: list[str] = []

        for iteration in range(self.MAX_TOOL_CALLS):
            response = await client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                tools=OPENAI_TOOLS,
                tool_choice="auto",
                timeout=45.0,
            )

            assistant_message = response.choices[0].message

            if assistant_message.tool_calls:
                messages.append(assistant_message)

                for tool_call in assistant_message.tool_calls:
                    if tool_call.function.name == "web_search":
                        args = json.loads(tool_call.function.arguments)
                        search_query = args.get("query", "")

                        logger.info(f"OpenAI tool call: web_search('{search_query}')")
                        search_results = await web_search_tool.search(search_query)

                        for result in search_results:
                            sources_used.append(result["link"])

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": json.dumps(search_results),
                            }
                        )
            else:
                return assistant_message.content or "", sources_used

        # Max iterations reached, get final response without tools
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            timeout=45.0,
        )
        return response.choices[0].message.content or "", sources_used

    async def _process_with_gemini(
        self,
        query: str,
        image_data: Optional[bytes] = None,
        image_mime_type: Optional[str] = None,
    ) -> tuple[str, list[str]]:
        """Process query using Gemini with tool calling, key rotation, and optional image."""
        from google.genai import types
        from google.genai.errors import ClientError

        from src.llm.key_rotator import gemini_key_rotator

        sources_used: list[str] = []

        # Define tools for Gemini
        tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="web_search",
                        description="Search the web for current information. Use this when you need up-to-date information, recent news, or facts you're not certain about.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "query": types.Schema(
                                    type=types.Type.STRING,
                                    description="The search query to look up",
                                )
                            },
                            required=["query"],
                        ),
                    )
                ]
            )
        ]

        # Build content parts - text only or multimodal with image
        parts: list[types.Part] = []
        if image_data and image_mime_type:
            parts.append(
                types.Part.from_bytes(data=image_data, mime_type=image_mime_type)
            )
            logger.info(
                f"Gemini processing multimodal query with image ({image_mime_type})"
            )
        parts.append(types.Part.from_text(text=query))

        contents: list[types.Content] = [types.Content(role="user", parts=parts)]

        async def call_with_rotation(config: types.GenerateContentConfig):
            """Make Gemini API call with automatic key rotation on errors."""
            num_keys = len(gemini_key_rotator._keys)
            last_error = None

            for attempt in range(num_keys):
                client = gemini_key_rotator.get_client()
                try:
                    return await client.aio.models.generate_content(
                        model=settings.gemini_model,
                        contents=contents,
                        config=config,
                    )
                except ClientError as e:
                    error_str = str(e).lower()
                    # Check if error warrants trying next key
                    is_rotatable_error = (
                        "429" in str(e)
                        or "quota" in error_str
                        or "rate" in error_str
                        or "api_key_invalid" in error_str
                        or "api key expired" in error_str
                        or "invalid_argument" in error_str
                        or "invalid api key" in error_str
                    )

                    if is_rotatable_error:
                        last_error = e
                        logger.warning(
                            f"API key {attempt + 1}/{num_keys} failed ({str(e)[:50]}...), rotating..."
                        )
                        gemini_key_rotator.rotate()
                    else:
                        raise

            raise last_error or ClientError("All API keys exhausted")

        for iteration in range(self.MAX_TOOL_CALLS):
            response = await call_with_rotation(
                types.GenerateContentConfig(
                    system_instruction=UNHINGED_SYSTEM_INSTRUCTION,
                    tools=tools,
                )
            )

            candidate = response.candidates[0]

            # Check for function calls in response parts
            function_calls = []
            for part in candidate.content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    function_calls.append(part.function_call)

            if function_calls:
                contents.append(candidate.content)

                function_responses = []
                for fc in function_calls:
                    if fc.name == "web_search":
                        search_query = fc.args.get("query", "")

                        logger.info(f"Gemini tool call: web_search('{search_query}')")
                        search_results = await web_search_tool.search(search_query)

                        for result in search_results:
                            sources_used.append(result["link"])

                        function_responses.append(
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name="web_search",
                                    response={"results": search_results},
                                )
                            )
                        )

                contents.append(types.Content(role="user", parts=function_responses))
            else:
                return response.text or "", sources_used

        # Max iterations, get final response without tools
        response = await call_with_rotation(
            types.GenerateContentConfig(
                system_instruction=UNHINGED_SYSTEM_INSTRUCTION,
            )
        )
        return response.text or "", sources_used


# Singleton instance
reply_agent = ReplyAgentService()
