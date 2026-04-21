import discord

COLOR_INFO = 0x00B4CC
COLOR_SUCCESS = 0x059669
COLOR_WARNING = 0xD97706
COLOR_ERROR = 0xDC2626


def build_embed(
    title: str = "",
    description: str = "",
    color: int = COLOR_INFO,
    fields: list[tuple[str, str, bool]] | None = None,
    footer: str = "",
    thumbnail: str = "",
    image: str = "",
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    if footer:
        embed.set_footer(text=footer)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if image:
        embed.set_image(url=image)
    return embed


def error_embed(description: str, title: str = "Error") -> discord.Embed:
    return build_embed(title=f"✗ {title}", description=description, color=COLOR_ERROR)


def success_embed(description: str, title: str = "Success") -> discord.Embed:
    return build_embed(title=f"✓ {title}", description=description, color=COLOR_SUCCESS)


def info_embed(description: str, title: str = "") -> discord.Embed:
    return build_embed(title=title, description=description, color=COLOR_INFO)


def warning_embed(description: str, title: str = "Warning") -> discord.Embed:
    return build_embed(title=f"⚠ {title}", description=description, color=COLOR_WARNING)
