"""Account for direct model calls using AstrBot's native provider statistics."""


async def record_usage(context, provider, response, *, umo: str, agent_type: str) -> None:
    usage = response.usage
    if usage is None:
        return
    await context.get_db().insert_provider_stat(
        umo=umo, provider_id=provider.meta().id, provider_model=provider.get_model(),
        status="error" if response.role == "err" else "completed",
        stats={"token_usage": {"input_other": usage.input_other,
                               "input_cached": usage.input_cached, "output": usage.output}},
        agent_type=agent_type,
    )
