// Native DSH client module. ConfigForms owns persistence, revisions and conflicts.
window.__ModuleLoader__.load({ id: 'dsh-fatfish-life', factory: require => {
  const React = require('react');
  const h = React.createElement;
  const labels = {
    reply: '回复规则', silent: '全局静默', groupCooldownSeconds: '群聊冷却（秒）',
    userCooldownSeconds: '用户冷却（秒）', dedupSeconds: '消息去重（秒）', normalKeywords: '正常时段触发词',
    busyWindows: '忙碌时间段（上海时间）', start: '开始时间', end: '结束时间', weekdays: '生效星期',
    voice: '语音', meme: '表情包', enabled: '启用', basePercent: '基础概率（%）',
    stepPercent: '每次未发增加（百分点）', maxPercent: '概率上限（%）', allowSynthesis: '允许可能收费的语音合成',
    provider: '配音服务', providers: '各配音服务参数', siliconflow: '硅基流动', elevenlabs: 'ElevenLabs', minimax: 'MiniMax',
    apiBase: '接口地址', modelId: '模型ID', voiceId: '音色ID', speed: '语速', envFile: '本机凭据文件路径（不填写密钥）',
    cooldownSeconds: '冷却（秒）', maxTextLength: '文字长度上限（0为不限）', manualTrigger: '允许手动触发',
    textAlongsideVoice: '语音同时发送文字', maxPerMessage: '每条回复最多表情数',
    workflows: '运营计划（执行器尚未注册）', recommend: 'B站推荐', times: '每日时间',
    commentEnabled: '推荐评论开关', maxVideos: '单次视频上限', study: '公开资料学习', time: '每日时间',
    comments: '评论回复', ownerOnly: '仅主人', daily: '每日总结与动态', publishEnabled: '动态发布开关',
  };
  const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  const fieldStyle = { display: 'flex', flexDirection: 'column', gap: 5, marginBottom: 14 };
  const inputStyle = { padding: '8px 10px', border: '1px solid var(--dsw-alias-border-l2, #aaa)',
    borderRadius: 7, color: 'inherit', background: 'transparent', width: '100%', boxSizing: 'border-box' };
  const buttonStyle = { padding: '7px 14px', borderRadius: 7, border: '1px solid currentColor',
    color: 'inherit', background: 'transparent', cursor: 'pointer' };
  const copy = value => structuredClone(value);

  function Card({ scope, view }) {
    const store = React.useMemo(() => ({ subscribe: fn => scope.subscribe(fn), read: () => scope.getSnapshot() }), [scope]);
    const accepted = React.useSyncExternalStore(store.subscribe, store.read, store.read);
    const [draft, setDraft] = React.useState(null);
    const [saving, setSaving] = React.useState(false);
    const [message, setMessage] = React.useState('');
    if (view === 'summary') return '回复门禁、忙碌时间、语音/表情概率、配音服务和运营目标计划。';
    if (!accepted.value) return h('p', null, '正在读取FatFish配置……');
    const value = draft?.value ?? accepted.value;
    const disabled = saving || !accepted.writable;
    function edit(path, next) {
      setMessage('');
      setDraft(previous => {
        const state = previous ?? { value: copy(accepted.value), base: copy(accepted.value), revision: accepted.revision };
        const updated = copy(state.value);
        let parent = updated;
        for (const key of path.slice(0, -1)) parent = parent[key];
        parent[path.at(-1)] = next;
        return { ...state, value: updated };
      });
    }
    function render(item, path) {
      const key = path.at(-1), id = 'fatfish-' + path.join('-'), label = labels[key] ?? key;
      if (key === 'weekdays') return h('fieldset', { key: id, style: { border: 0, padding: 0, marginBottom: 14 } },
        h('legend', null, label), ...weekdays.map((day, index) => h('label', { key: day, style: { marginRight: 12 } },
          h('input', { type: 'checkbox', disabled, checked: item.includes(index), onChange: event =>
            edit(path, event.target.checked ? [...item, index].sort() : item.filter(value => value !== index)) }), day)));
      if (Array.isArray(item)) return h('fieldset', { key: id, style: { border: 0, padding: 0, marginBottom: 18 } },
        h('legend', { style: { fontWeight: 600 } }, label),
        ...item.map((entry, index) => h('div', { key: index, style: { borderLeft: '2px solid #8886', paddingLeft: 12, marginTop: 10 } },
          render(entry, [...path, index]), h('button', { type: 'button', style: buttonStyle, disabled,
            onClick: () => edit(path, item.filter((_, position) => position !== index)) }, '移除此项'))),
        h('button', { type: 'button', style: { ...buttonStyle, marginTop: 10 }, disabled, onClick: () =>
          edit(path, [...item, key === 'busyWindows' ? { start: '09:00', end: '12:00', weekdays: [0,1,2,3,4,5,6] } : '']) }, '添加一项'));
      if (item && typeof item === 'object') return h('details', { key: id, open: path.length === 1,
        style: { borderTop: '1px solid #8885', paddingTop: 14, marginBottom: 18 } },
        h('summary', { style: { fontWeight: 600, cursor: 'pointer', marginBottom: 14 } },
          typeof key === 'number' ? '第' + (key + 1) + '项' : label),
        ...Object.entries(item).map(([child, entry]) => render(entry, [...path, child])));
      if (typeof item === 'boolean') return h('label', { key: id, htmlFor: id, style: { ...fieldStyle, flexDirection: 'row' } },
        h('input', { id, type: 'checkbox', disabled, checked: item, onChange: event => edit(path, event.target.checked) }), label);
      if (key === 'provider') return h('label', { key: id, htmlFor: id, style: fieldStyle }, label,
        h('select', { id, value: item, disabled, style: inputStyle, onChange: event => edit(path, event.target.value) },
          ...['siliconflow', 'elevenlabs', 'minimax'].map(provider => h('option', { key: provider, value: provider }, labels[provider]))));
      const timed = ['start', 'end', 'time'].includes(key) || path.at(-2) === 'times';
      const numeric = typeof item === 'number';
      return h('label', { key: id, htmlFor: id, style: fieldStyle }, typeof key === 'number' ? '第' + (key + 1) + '项' : label,
        h('input', { id, type: numeric ? 'number' : timed ? 'time' : 'text', value: item ?? '', disabled,
          min: numeric ? 0 : undefined, max: String(key).endsWith('Percent') ? 100 : undefined,
          step: numeric ? key === 'speed' ? .05 : 1 : undefined, style: inputStyle,
          onChange: event => edit(path, numeric ? event.target.value === '' ? '' : Number(event.target.value) : event.target.value) }));
    }
    async function save(event) {
      event.preventDefault();
      if (!draft || saving) return;
      const values = draft.value;
      for (const channel of [values.voice, values.meme, values.workflows.daily]) {
        if (channel.basePercent > channel.maxPercent) { setMessage('基础概率不能高于上限，请调整后保存。'); return; }
      }
      if (values.busyWindows.some(window => window.start === window.end)) { setMessage('忙碌时间的开始和结束不能相同。'); return; }
      const ops = Object.keys(values).filter(key => JSON.stringify(values[key]) !== JSON.stringify(draft.base[key]))
        .map(key => ({ op: 'set', path: [key], value: values[key] }));
      if (!ops.length) { setDraft(null); return; }
      setSaving(true);
      try {
        const saved = await scope.mutate(ops, draft.revision);
        if (saved) { setDraft(null); setMessage('已保存到DSH，运行参数同步更新。'); }
        else setMessage('保存未通过，可能有其他页面同时修改。草稿已保留，请重新加载配置后再修改。');
      } catch { setMessage('保存失败，草稿已保留。请检查DSH连接与运行日志。'); }
      finally { setSaving(false); }
    }
    return h('form', { onSubmit: save, style: { maxWidth: 850, paddingBottom: 35 } },
      h('p', { style: { lineHeight: 1.7 } }, '此页复用DSH配置存储。QQ尚未切换；媒体最终出口及运营执行器仍在迁移，计划开关目前不会自动发动态或评论。凭据只填写本机文件路径。'),
      ...Object.entries(value).map(([key, item]) => render(item, [key])),
      h('div', { style: { display: 'flex', gap: 12 } },
        h('button', { type: 'submit', disabled: disabled || !draft, style: buttonStyle }, saving ? '保存中……' : '保存参数'),
        h('button', { type: 'button', disabled: saving || !draft, style: buttonStyle,
          onClick: () => { setDraft(null); setMessage('已恢复当前生效值。'); } }, '放弃修改')),
      h('p', { role: 'status', style: { minHeight: 24 } }, message));
  }
  return { inject: ['slots', 'configForms'], apply(ctx) {
    const scope = ctx.configForms.get('fatfish-control');
    ctx.effect(() => ctx.configForms.whileServed(['fatfish-control'], () => ctx.slots.inject('plugins.item', () =>
      ctx.slots.register({ name: 'plugins.item', id: 'fatfish-control', order: 50,
        label: 'FatFishLife 管理', inject: () => ({ scope }) }, Card))));
  } };
} });
