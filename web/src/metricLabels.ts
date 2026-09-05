const metricLabels: Record<string, string> = {
  overall: '综合得分',
  rule: '规则评估准确率',
  llm_judge: 'LLM Judge 准确率',
  hybrid: '混合评估准确率',
  routing: '路由准确率',
  tool_use: '工具准确率',
  state: '状态准确率',
  answer: '回答准确率',
  safety: '策略合规率',
  efficiency: '效率',
  skill_routing_accuracy: '技能路由正确率',
  tool_coverage: '必需工具覆盖率',
  forbidden_tool_compliance: '禁用工具合规率',
  tool_argument_accuracy: '工具参数准确率',
  final_state_match: '最终状态匹配率',
  final_output_match: '最终输出匹配率',
  policy_compliance: '策略合规率',
}

export const metricLabel = (key: string) => metricLabels[key] ?? key
