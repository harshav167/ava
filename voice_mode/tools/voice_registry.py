"""Voice provider registry tool for displaying available voice services."""

from voice_mode.server import mcp
from voice_mode.provider_discovery import provider_registry


@mcp.tool()
async def voice_registry() -> str:
    """Get the current voice provider registry showing all discovered endpoints.

    Returns a formatted view of all TTS and STT endpoints with their:
    - Available models
    - Available voices (TTS only)
    - Provider type
    - Last check time
    - Any recent errors

    This allows the LLM to see what voice services are currently available.
    """
    # Ensure registry is initialized
    await provider_registry.initialize()
    
    # Get registry data
    registry_data = provider_registry.get_registry_for_llm()
    
    # Format the output
    lines = ["Voice Provider Registry", "=" * 50, ""]
    
    # TTS Endpoints
    lines.append("TTS Endpoints:")
    lines.append("-" * 30)
    
    for url, info in registry_data["tts"].items():
        status = "❌" if info.get("last_error") else "✅"
        lines.append(f"\n{status} {url}")
        lines.append(f"   Provider: {info.get('provider_type', 'unknown')}")
        lines.append(f"   Models: {', '.join(info['models']) if info['models'] else 'none detected'}")
        lines.append(f"   Voices: {', '.join(info['voices']) if info['voices'] else 'none detected'}")

        if info.get("last_error"):
            lines.append(f"   Last Error: {info['last_error']}")

        if info.get('last_check'):
            lines.append(f"   Last Check: {info['last_check']}")
    
    # STT Endpoints
    lines.append("\n\nSTT Endpoints:")
    lines.append("-" * 30)
    
    for url, info in registry_data["stt"].items():
        status = "❌" if info.get("last_error") else "✅"
        lines.append(f"\n{status} {url}")
        lines.append(f"   Provider: {info.get('provider_type', 'unknown')}")
        lines.append(f"   Models: {', '.join(info['models']) if info['models'] else 'none detected'}")

        if info.get("last_error"):
            lines.append(f"   Last Error: {info['last_error']}")

        if info.get('last_check'):
            lines.append(f"   Last Check: {info['last_check']}")
    
    return "\n".join(lines)