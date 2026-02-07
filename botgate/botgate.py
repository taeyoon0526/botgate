from typing import List, Optional

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

LOG_COOLDOWN_SECONDS = 30


class ApproveButton(discord.ui.Button):
    def __init__(self, cog: "BotGate", guild_id: int, bot_id: int):
        custom_id = f"botgate_approve:{guild_id}:{bot_id}"
        super().__init__(
            label="허용(서버 소유자만)",
            style=discord.ButtonStyle.success,
            custom_id=custom_id,
        )
        self.cog = cog
        self.guild_id = guild_id
        self.bot_id = bot_id

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await interaction.response.send_message("서버 정보가 일치하지 않습니다.", ephemeral=True)
            return
        if not await self.cog._user_can_approve(interaction.user, interaction.guild):
            await interaction.response.send_message("승인 권한이 없습니다.", ephemeral=True)
            return

        await self.cog._approve_bot(
            interaction.guild,
            self.bot_id,
            approved_by=interaction.user.id,
            source="button",
        )
        await interaction.response.send_message("승인 완료. 허용 목록에 추가했습니다.", ephemeral=True)


class InviteLinkButton(discord.ui.Button):
    def __init__(self, bot_id: int, url: str):
        super().__init__(
            label="봇 초대 링크",
            style=discord.ButtonStyle.link,
            url=url,
        )
        self.bot_id = bot_id

def _add_layout_text(
    view: discord.ui.LayoutView,
    title: Optional[str],
    lines: Optional[List[str]],
    footer: Optional[str],
    *,
    accent_color: Optional[int] = None,
    use_container: bool = False,
) -> None:
    container: Optional[discord.ui.Container] = None
    if use_container:
        container = discord.ui.Container(
            accent_color=accent_color or int(discord.Color.blurple())
        )
        view.add_item(container)
    if title:
        title_display = discord.ui.TextDisplay(f"## {title}")
        if container:
            container.add_item(title_display)
            container.add_item(
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small)
            )
        else:
            view.add_item(title_display)
            view.add_item(
                discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small)
            )
    if lines:
        for line in lines:
            if container:
                container.add_item(discord.ui.TextDisplay(line))
            else:
                view.add_item(discord.ui.TextDisplay(line))
    if footer:
        separator = discord.ui.Separator(
            visible=False, spacing=discord.SeparatorSpacing.small
        )
        footer_display = discord.ui.TextDisplay(f"*{footer}*")
        if container:
            container.add_item(separator)
            container.add_item(footer_display)
        else:
            view.add_item(separator)
            view.add_item(footer_display)


class BotGateLayoutView(discord.ui.LayoutView):
    def __init__(
        self,
        *,
        title: Optional[str] = None,
        lines: Optional[List[str]] = None,
        footer: Optional[str] = None,
        actions: Optional[List[discord.ui.Item]] = None,
        accent_color: Optional[int] = None,
        use_container: bool = False,
    ):
        super().__init__(timeout=None)
        _add_layout_text(
            self,
            title,
            lines,
            footer,
            accent_color=accent_color,
            use_container=use_container,
        )
        if actions:
            row = discord.ui.ActionRow()
            for item in actions:
                row.add_item(item)
            self.add_item(row)


class ApproveLayoutView(BotGateLayoutView):
    def __init__(
        self,
        cog: "BotGate",
        guild_id: int,
        bot_id: int,
        *,
        title: Optional[str] = None,
        lines: Optional[List[str]] = None,
        footer: Optional[str] = None,
        accent_color: Optional[int] = None,
    ):
        self.cog = cog
        self.guild_id = guild_id
        self.bot_id = bot_id
        self.tracks_approval = True
        actions = [
            ApproveButton(cog, guild_id, bot_id),
            InviteLinkButton(bot_id, cog._oauth_url(bot_id)),
        ]
        super().__init__(
            title=title,
            lines=lines,
            footer=footer,
            actions=actions,
            accent_color=accent_color,
            use_container=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        await self.cog._log_console(f"[BotGate] View error: {error}")


class BotGate(commands.Cog):
    """서버에 들어오는 봇을 자동 킥하고 승인 버튼을 제공"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9045229001, force_registration=True)
        self.config.register_guild(
            enabled=False,
            log_channel_id=None,
            approved_role_id=None,
            allowlist={},
            approver_user_ids=[],
            approver_role_ids=[],
            approver_owner_always=True,
            pending_approvals=[],
        )
        self._log_cooldown = {}
        self._intents_warned = False

    async def cog_load(self):
        await self._maybe_warn_intents()
        await self._restore_pending_views()

    async def _maybe_warn_intents(self):
        if self._intents_warned:
            return
        self._intents_warned = True
        if not self.bot.intents.members:
            await self._log_console("[BotGate] WARNING: members intent가 꺼져 있습니다.")
            await self._broadcast_intent_warning()

    async def _broadcast_intent_warning(self):
        for guild in self.bot.guilds:
            log_channel_id = await self.config.guild(guild).log_channel_id()
            if not log_channel_id:
                continue
            channel = guild.get_channel(log_channel_id)
            if not channel:
                continue
            try:
                view = BotGateLayoutView(
                    title="⚠️ BotGate 경고",
                    lines=["members intent가 꺼져 있어 봇 입장 감지가 동작하지 않을 수 있습니다."],
                    accent_color=int(discord.Color.orange()),
                    use_container=True,
                )
                await channel.send(view=view)
            except Exception:
                continue

    async def _log_console(self, message: str):
        print(message)

    async def _send_log(
        self,
        guild: discord.Guild,
        view: discord.ui.LayoutView,
        *,
        content: Optional[str] = None,
    ):
        log_channel_id = await self.config.guild(guild).log_channel_id()
        if not log_channel_id:
            await self._log_console(f"[BotGate] log channel not set: {guild.id}")
            return
        channel = guild.get_channel(log_channel_id)
        if not channel:
            await self._log_console(f"[BotGate] log channel missing: {guild.id}")
            return
        try:
            message = await channel.send(content=content, view=view)
            try:
                self.bot.add_view(view, message_id=message.id)
            except Exception:
                pass
            if getattr(view, "tracks_approval", False):
                bot_id = getattr(view, "bot_id", None)
                if bot_id is not None:
                    await self._store_pending_approval(guild.id, bot_id, message.id)
        except Exception as exc:
            await self._log_console(f"[BotGate] failed to log: {exc}")

    def _cooldown_hit(self, guild_id: int, bot_id: int) -> bool:
        now = discord.utils.utcnow()
        key = (guild_id, bot_id)
        last = self._log_cooldown.get(key)
        if last and (now - last).total_seconds() < LOG_COOLDOWN_SECONDS:
            return True
        self._log_cooldown[key] = now
        return False

    def _oauth_url(self, bot_id: int) -> str:
        return (
            "https://discord.com/oauth2/authorize"
            f"?client_id={bot_id}&permissions=8&integration_type=0&scope=bot"
        )

    async def _approve_bot(self, guild: discord.Guild, bot_id: int, approved_by: int, source: str):
        now = discord.utils.utcnow().isoformat()
        allowlist = await self.config.guild(guild).allowlist()
        allowlist[str(bot_id)] = {"approved_by": approved_by, "approved_at": now}
        await self.config.guild(guild).allowlist.set(allowlist)

        url = self._oauth_url(bot_id)
        view = BotGateLayoutView(
            title="✅ 봇 승인 완료",
            lines=[
                f"승인자: <@{approved_by}>",
                f"봇 ID: `{bot_id}`",
                f"승인 시각: <t:{int(discord.utils.utcnow().timestamp())}:F>",
            ],
            footer=f"승인 경로: {source}",
            actions=[InviteLinkButton(bot_id, url)],
            accent_color=int(discord.Color.green()),
            use_container=True,
        )
        await self._send_log(guild, view)
        await self._remove_pending_approval(guild.id, bot_id)

        member = guild.get_member(bot_id)
        if member and member.bot:
            await self._assign_role_if_needed(member)

    async def _user_can_approve(self, user: discord.abc.User, guild: discord.Guild) -> bool:
        if await self.bot.is_owner(user):
            return True
        conf = self.config.guild(guild)
        owner_always = await conf.approver_owner_always()
        if owner_always and user.id == guild.owner_id:
            return True
        user_ids = await conf.approver_user_ids()
        if user.id in user_ids:
            return True
        role_ids = await conf.approver_role_ids()
        member = guild.get_member(user.id)
        if member:
            return any(role.id in role_ids for role in member.roles)
        return False

    async def _is_allowed(self, guild: discord.Guild, bot_id: int) -> bool:
        allowlist = await self.config.guild(guild).allowlist()
        return str(bot_id) in allowlist

    async def _assign_role_if_needed(self, member: discord.Member):
        role_id = await self.config.guild(member.guild).approved_role_id()
        if not role_id:
            return
        role = member.guild.get_role(role_id)
        if not role:
            return
        bot_member = member.guild.me
        if not bot_member or not bot_member.guild_permissions.manage_roles:
            return
        if role >= bot_member.top_role:
            return
        try:
            await member.add_roles(role, reason="BotGate 승인 봇 자동 역할 부여")
        except Exception:
            return

    async def _store_pending_approval(self, guild_id: int, bot_id: int, message_id: int):
        conf = self.config.guild_from_id(guild_id)
        pending = await conf.pending_approvals()
        for entry in pending:
            if entry.get("bot_id") == bot_id and entry.get("message_id") == message_id:
                return
        pending.append({"bot_id": bot_id, "message_id": message_id})
        await conf.pending_approvals.set(pending[-200:])

    async def _remove_pending_approval(self, guild_id: int, bot_id: int):
        conf = self.config.guild_from_id(guild_id)
        pending = await conf.pending_approvals()
        new_pending = [entry for entry in pending if entry.get("bot_id") != bot_id]
        if len(new_pending) != len(pending):
            await conf.pending_approvals.set(new_pending)

    async def _restore_pending_views(self):
        for guild in self.bot.guilds:
            conf = self.config.guild(guild)
            pending = await conf.pending_approvals()
            if not pending:
                continue
            cleaned = []
            for entry in pending:
                bot_id = entry.get("bot_id")
                message_id = entry.get("message_id")
                if not bot_id or not message_id:
                    continue
                view = ApproveLayoutView(self, guild.id, bot_id)
                try:
                    self.bot.add_view(view, message_id=message_id)
                    cleaned.append(entry)
                except Exception:
                    continue
            if len(cleaned) != len(pending):
                await conf.pending_approvals.set(cleaned)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.guild:
            return
        if not member.bot:
            return
        if not self.bot.user or member.id == self.bot.user.id:
            return

        await self._maybe_warn_intents()

        enabled = await self.config.guild(member.guild).enabled()
        if not enabled:
            return

        allowed = await self._is_allowed(member.guild, member.id)
        if allowed:
            await self._assign_role_if_needed(member)
            if not self._cooldown_hit(member.guild.id, member.id):
                view = BotGateLayoutView(
                    title="✅ 승인된 봇 입장 확인",
                    lines=[f"{member}(`{member.id}`)"],
                    accent_color=int(discord.Color.green()),
                    use_container=True,
                )
                await self._send_log(member.guild, view)
            return

        kick_result = "킥 성공"
        kick_error = None
        try:
            await member.kick(reason="BotGate: 미승인 봇 자동 킥")
        except Exception as exc:
            kick_result = "킥 실패"
            kick_error = str(exc)

        if self._cooldown_hit(member.guild.id, member.id):
            return

        lines = [
            f"**봇:** {member}(`{member.id}`)",
            f"**서버:** {member.guild.name}(`{member.guild.id}`)",
            f"**감지 시각:** <t:{int(discord.utils.utcnow().timestamp())}:F>",
            f"**처리 결과:** {kick_result}",
        ]
        if kick_error:
            lines.append(f"**실패 사유:** {kick_error[:1000]}")
        view = ApproveLayoutView(
            self,
            member.guild.id,
            member.id,
            title="🚨 승인되지 않은 봇 감지",
            lines=lines,
            footer="수동 승인: [p]botgate allow <bot_id> | approver 추가: [p]botgate approver adduser @user",
            accent_color=int(discord.Color.red()),
        )
        await self._send_log(member.guild, view)

    @commands.group(name="botgate")
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def botgate(self, ctx: commands.Context):
        """BotGate 설정"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @botgate.command(name="toggle")
    async def botgate_toggle(self, ctx: commands.Context):
        """기능 ON/OFF"""
        current = await self.config.guild(ctx.guild).enabled()
        new_value = not current
        await self.config.guild(ctx.guild).enabled.set(new_value)
        await ctx.send(f"BotGate가 {'ON' if new_value else 'OFF'} 상태입니다.")

    @botgate.command(name="channel")
    async def botgate_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """로그 채널 설정"""
        await self.config.guild(ctx.guild).log_channel_id.set(channel.id)
        await ctx.send(f"로그 채널을 {channel.mention}로 설정했습니다.")

    @botgate.command(name="setrole")
    async def botgate_setrole(self, ctx: commands.Context, *, role_arg: Optional[str] = None):
        """승인된 봇에게 자동 부여할 역할 설정/해제"""
        if role_arg is None or role_arg.lower() == "none":
            await self.config.guild(ctx.guild).approved_role_id.set(None)
            await ctx.send("자동 역할 부여를 해제했습니다.")
            return

        converter = commands.RoleConverter()
        try:
            role = await converter.convert(ctx, role_arg)
        except commands.BadArgument:
            await ctx.send("역할을 찾을 수 없습니다. 멘션 또는 역할 이름을 사용하세요.")
            return

        await self.config.guild(ctx.guild).approved_role_id.set(role.id)
        await ctx.send(f"승인된 봇 자동 역할을 {role.mention}로 설정했습니다.")

    @botgate.command(name="status")
    async def botgate_status(self, ctx: commands.Context):
        """현재 설정 요약"""
        conf = self.config.guild(ctx.guild)
        enabled = await conf.enabled()
        log_channel_id = await conf.log_channel_id()
        role_id = await conf.approved_role_id()
        allowlist = await conf.allowlist()

        owner_always = await conf.approver_owner_always()
        approver_user_ids = await conf.approver_user_ids()
        approver_role_ids = await conf.approver_role_ids()
        user_mentions = " ".join(f"<@{uid}>" for uid in approver_user_ids[:10]) or "없음"
        role_mentions = " ".join(f"<@&{rid}>" for rid in approver_role_ids[:10]) or "없음"
        if len(approver_user_ids) > 10:
            user_mentions += f" 외 {len(approver_user_ids) - 10}명"
        if len(approver_role_ids) > 10:
            role_mentions += f" 외 {len(approver_role_ids) - 10}개"
        view = BotGateLayoutView(
            title="BotGate 상태",
            lines=[
                f"**활성화:** {'ON' if enabled else 'OFF'}",
                f"**로그 채널:** <#{log_channel_id}>" if log_channel_id else "**로그 채널:** 미설정",
                f"**승인 역할:** <@&{role_id}>" if role_id else "**승인 역할:** 미설정",
                f"**허용 목록 수:** {len(allowlist)}",
                (
                    "**승인 버튼 권한자**\n"
                    f"소유자 항상 허용: {'ON' if owner_always else 'OFF'}\n"
                    f"유저: {user_mentions}\n"
                    f"역할: {role_mentions}"
                ),
            ],
            accent_color=int(discord.Color.blurple()),
            use_container=True,
        )
        await ctx.send(view=view)

    @botgate.command(name="allow")
    async def botgate_allow(self, ctx: commands.Context, bot_id: int):
        """봇 수동 허용"""
        await self._approve_bot(ctx.guild, bot_id, approved_by=ctx.author.id, source="command")
        await ctx.send(f"`{bot_id}`를 허용 목록에 추가했습니다.")

    @botgate.command(name="deny")
    async def botgate_deny(self, ctx: commands.Context, bot_id: int):
        """봇 수동 차단(허용 목록 제거)"""
        allowlist = await self.config.guild(ctx.guild).allowlist()
        if str(bot_id) in allowlist:
            allowlist.pop(str(bot_id), None)
            await self.config.guild(ctx.guild).allowlist.set(allowlist)
            await ctx.send(f"`{bot_id}`를 허용 목록에서 제거했습니다.")
            return
        await ctx.send("해당 봇은 허용 목록에 없습니다.")

    async def _ensure_owner_only(self, ctx: commands.Context) -> bool:
        if not ctx.guild:
            return False
        if ctx.author.id == ctx.guild.owner_id:
            return True
        return await ctx.bot.is_owner(ctx.author)

    @botgate.group(name="approver")
    @commands.guild_only()
    async def botgate_approver(self, ctx: commands.Context):
        """승인 버튼 권한자 관리(서버 소유자 전용)"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    async def _owner_only_or_reply(self, ctx: commands.Context) -> bool:
        if await self._ensure_owner_only(ctx):
            return True
        view = BotGateLayoutView(
            title="권한 부족",
            lines=["이 명령어는 서버 소유자만 사용할 수 있습니다."],
            accent_color=int(discord.Color.red()),
            use_container=True,
        )
        await ctx.send(view=view)
        return False

    @botgate_approver.command(name="adduser")
    async def botgate_approver_adduser(self, ctx: commands.Context, user: discord.Member):
        """승인 버튼 권한 유저 추가"""
        if not await self._owner_only_or_reply(ctx):
            return
        conf = self.config.guild(ctx.guild)
        user_ids = await conf.approver_user_ids()
        if user.id in user_ids:
            view = BotGateLayoutView(
                title="이미 등록됨",
                lines=[f"{user.mention}는 이미 승인 권한자입니다."],
                accent_color=int(discord.Color.orange()),
                use_container=True,
            )
            await ctx.send(view=view)
            return
        user_ids.append(user.id)
        await conf.approver_user_ids.set(user_ids)
        view = BotGateLayoutView(
            title="승인 권한자 추가",
            lines=[f"{user.mention}를 승인 권한자로 추가했습니다."],
            accent_color=int(discord.Color.green()),
            use_container=True,
        )
        await ctx.send(view=view)

    @botgate_approver.command(name="deluser")
    async def botgate_approver_deluser(self, ctx: commands.Context, user: discord.Member):
        """승인 버튼 권한 유저 삭제"""
        if not await self._owner_only_or_reply(ctx):
            return
        conf = self.config.guild(ctx.guild)
        user_ids = await conf.approver_user_ids()
        if user.id not in user_ids:
            view = BotGateLayoutView(
                title="미등록",
                lines=[f"{user.mention}는 승인 권한자가 아닙니다."],
                accent_color=int(discord.Color.orange()),
                use_container=True,
            )
            await ctx.send(view=view)
            return
        user_ids.remove(user.id)
        await conf.approver_user_ids.set(user_ids)
        view = BotGateLayoutView(
            title="승인 권한자 삭제",
            lines=[f"{user.mention}를 승인 권한자에서 제거했습니다."],
            accent_color=int(discord.Color.green()),
            use_container=True,
        )
        await ctx.send(view=view)

    @botgate_approver.command(name="addrole")
    async def botgate_approver_addrole(self, ctx: commands.Context, role: discord.Role):
        """승인 버튼 권한 역할 추가"""
        if not await self._owner_only_or_reply(ctx):
            return
        conf = self.config.guild(ctx.guild)
        role_ids = await conf.approver_role_ids()
        if role.id in role_ids:
            view = BotGateLayoutView(
                title="이미 등록됨",
                lines=[f"{role.mention}는 이미 승인 권한 역할입니다."],
                accent_color=int(discord.Color.orange()),
                use_container=True,
            )
            await ctx.send(view=view)
            return
        role_ids.append(role.id)
        await conf.approver_role_ids.set(role_ids)
        view = BotGateLayoutView(
            title="승인 권한 역할 추가",
            lines=[f"{role.mention}을 승인 권한 역할로 추가했습니다."],
            accent_color=int(discord.Color.green()),
            use_container=True,
        )
        await ctx.send(view=view)

    @botgate_approver.command(name="delrole")
    async def botgate_approver_delrole(self, ctx: commands.Context, role: discord.Role):
        """승인 버튼 권한 역할 삭제"""
        if not await self._owner_only_or_reply(ctx):
            return
        conf = self.config.guild(ctx.guild)
        role_ids = await conf.approver_role_ids()
        if role.id not in role_ids:
            view = BotGateLayoutView(
                title="미등록",
                lines=[f"{role.mention}는 승인 권한 역할이 아닙니다."],
                accent_color=int(discord.Color.orange()),
                use_container=True,
            )
            await ctx.send(view=view)
            return
        role_ids.remove(role.id)
        await conf.approver_role_ids.set(role_ids)
        view = BotGateLayoutView(
            title="승인 권한 역할 삭제",
            lines=[f"{role.mention}을 승인 권한 역할에서 제거했습니다."],
            accent_color=int(discord.Color.green()),
            use_container=True,
        )
        await ctx.send(view=view)

    @botgate_approver.command(name="list")
    async def botgate_approver_list(self, ctx: commands.Context):
        """승인 버튼 권한 목록"""
        if not await self._owner_only_or_reply(ctx):
            return
        conf = self.config.guild(ctx.guild)
        owner_always = await conf.approver_owner_always()
        user_ids = await conf.approver_user_ids()
        role_ids = await conf.approver_role_ids()
        user_mentions = " ".join(f"<@{uid}>" for uid in user_ids[:15]) or "없음"
        role_mentions = " ".join(f"<@&{rid}>" for rid in role_ids[:15]) or "없음"
        if len(user_ids) > 15:
            user_mentions += f" 외 {len(user_ids) - 15}명"
        if len(role_ids) > 15:
            role_mentions += f" 외 {len(role_ids) - 15}개"
        view = BotGateLayoutView(
            title="승인 버튼 권한자 목록",
            lines=[
                f"**소유자 항상 허용:** {'ON' if owner_always else 'OFF'}",
                f"**유저:** {user_mentions}",
                f"**역할:** {role_mentions}",
            ],
            accent_color=int(discord.Color.blurple()),
            use_container=True,
        )
        await ctx.send(view=view)

    @botgate_approver.command(name="reset")
    async def botgate_approver_reset(self, ctx: commands.Context):
        """승인 버튼 권한자 초기화"""
        if not await self._owner_only_or_reply(ctx):
            return
        conf = self.config.guild(ctx.guild)
        await conf.approver_user_ids.set([])
        await conf.approver_role_ids.set([])
        await conf.approver_owner_always.set(True)
        view = BotGateLayoutView(
            title="초기화 완료",
            lines=["승인 권한자를 모두 초기화했습니다. (소유자 항상 허용: ON)"],
            accent_color=int(discord.Color.green()),
            use_container=True,
        )
        await ctx.send(view=view)

    @botgate_approver.command(name="owneralways")
    async def botgate_approver_owneralways(self, ctx: commands.Context, value: bool):
        """소유자 항상 허용 설정"""
        if not await self._owner_only_or_reply(ctx):
            return
        await self.config.guild(ctx.guild).approver_owner_always.set(value)
        view = BotGateLayoutView(
            title="설정 변경",
            lines=[f"소유자 항상 허용: {'ON' if value else 'OFF'}"],
            accent_color=int(discord.Color.green()),
            use_container=True,
        )
        await ctx.send(view=view)
