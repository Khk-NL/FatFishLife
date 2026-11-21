import { readProviderQuota } from './persona/codex-routing.mjs';

export function parseWechatServiceQuery(text) {
  const query = text.trim().toLowerCase().replace(/[\s，、,。？?！!]/gu, '');
  if (/^\/(?:model|模型)$/u.test(query)) return 'model';
  if (/^\/(?:model|模型)(?:codex|gpt|gpt-6\.2-sol)$/u.test(query)
      || /^(?:请|帮我|麻烦)?(?:把模型)?(?:切换|切|换)(?:模型)?(?:为|成|到|用)(?:codex|gpt|gpt-6\.2-sol)$/u.test(query)) {
    return 'use-codex';
  }
  if (/^\/(?:model|模型)(?:deepseek|auto)$/u.test(query)
      || /^(?:请|帮我|麻烦)?(?:把模型)?(?:切换|切|换)(?:模型)?(?:回到|回来|回|为|成|到|用)deepseek$/u.test(query)) {
    return 'use-deepseek';
  }
  if (/^(?:(?:请|帮我|麻烦)(?:查一下|看一下|告诉我))?(?:鲸鲸|你|本鱼)?(?:现在|目前|当前|刚才|上一条|上次)?(?:在用|用了|用的是?|使用的是?|用|是)?(?:什么|哪个|哪一个)(?:模型|模块)(?:呀|啊|呢|吗)?$/u.test(query)) {
    return 'model';
  }
  if (/^\/(?:quota|额度)(?:全部)?$/u.test(query)) return 'both';
  if (/^\/(?:quota|额度)(?:codex|workbuddy)$/u.test(query)) return query.endsWith('codex') ? 'codex' : 'workbuddy';
  const codex = query.includes('codex');
  const workBuddy = query.includes('workbuddy');
  if ((!codex && !workBuddy) || !/(额度|用量|积分|余量|余额|还剩|还有|多少)/u.test(query)) return;
  const remainder = query.replace(/codex|workbuddy|的|和|及|还有|还剩|有多少|剩余|多少|额度|限额|用量|积分|余量|余额|(?:5|五)小时|(?:7|七)天|本周|周|现在|目前|请|帮我|给我|查一下|查下|查|看一下|看下|看看|告诉我|一下|啊|呢|吗|呀|吧/gu, '');
  if (remainder) return;
  return codex && workBuddy ? 'both' : codex ? 'codex' : 'workbuddy';
}

function percent(remaining, resetsAt) {
  return Number.isFinite(remaining) && remaining >= 0 && remaining <= 100
    && Number.isFinite(resetsAt) && resetsAt * 1000 > Date.now() ? `${remaining}%` : '暂时查不到';
}

export async function formatWechatQuota(ctx, scope) {
  const providers = scope === 'both' ? ['codex', 'workbuddy'] : [scope];
  const rows = await Promise.all(providers.map(async provider => {
    const report = await readProviderQuota(ctx, provider);
    if (provider === 'codex') {
      if (!report) return 'Codex 额度暂时查不到';
      return `Codex 五小时余 ${percent(report.remaining, report.resetsAt)}，七天余 ${percent(report.weeklyRemaining, report.weeklyResetsAt)}`;
    }
    const credits = report?.totalCredits;
    return Number.isFinite(credits) && credits >= 0
      ? `WorkBuddy 还有 ${credits.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 积分`
      : 'WorkBuddy 积分暂时查不到';
  }));
  return rows.join('\n');
}
