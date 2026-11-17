package com.searchagent.career.task;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

import org.springframework.stereotype.Component;

@Component
class InterviewQuestions {
    enum Phase { WARMUP, CORE, SCENARIO }

    record Question(String id, int version, int gradingVersion, Phase phase, String topic, String prompt,
            List<String> rubric, String sourceName, String sourceUrl) {}

    private record Template(String topic, String prompt, String... rubric) {
        Question forRole(String id, Phase phase, String title) {
            return new Question(id, 1, 1, phase, topic, prompt.formatted(title), List.of(rubric), "内置模拟题库", null);
        }
    }

    private static final List<Template> WARMUP = List.of(
            new Template("自我介绍", "请用一分钟介绍自己，并选一段经历说明你与「%s」岗位的匹配点。",
                    "与岗位相关的经历", "个人贡献", "表达有主次"),
            new Template("求职动机", "你为什么想做「%s」？哪段经历影响了这个选择？",
                    "动机具体", "真实经历与岗位要求的联系"),
            new Template("能力匹配", "「%s」岗位的要求中，你最有把握的是哪一项？请举例说明。",
                    "准确理解岗位要求", "说明自己的行动和结果"),
            new Template("上手计划", "如果加入团队担任「%s」，你希望第一周了解哪些事情？为什么？",
                    "了解职责和协作关系", "排序有依据", "可执行的了解方式"),
            new Template("成长方向", "为了胜任「%s」，你最近主动补足了哪项能力？怎样判断自己有进步？",
                    "行动清晰", "进步有可观察的证据"));

    private static final List<Template> CORE = List.of(
            new Template("难题定位", "说一次能体现「%s」岗位能力的难题。你怎样缩小问题范围并验证结论？",
                    "问题与排查步骤", "验证依据", "说明个人贡献"),
            new Template("方案选择", "请分享一项和「%s」有关的任务，你怎样在备选方案之间做决定？",
                    "明确约束", "比较备选方案", "复查选型结果"),
            new Template("成果验证", "如果用一个成果证明你能胜任「%s」，你会选哪个？怎样核实它确实有效？",
                    "目标与结果对应", "具体证据", "说明证据的局限"),
            new Template("个人贡献", "选一个能体现「%s」岗位能力的团队项目。你负责哪些部分？如何交付给下一位同事？",
                    "职责边界", "具体产出", "交接方法"),
            new Template("需求澄清", "作为「%s」接到一个描述模糊的任务，你会先问哪些问题？怎样确认理解一致？",
                    "澄清目标及约束", "对齐验收标准", "确定沟通对象"),
            new Template("质量检查", "回顾一项与你应聘「%s」相关的交付，哪些检查帮助你在发布前发现问题？",
                    "解释风险与检查的关系", "台前或台后的检查证据"),
            new Template("排期估算", "如果你以「%s」身份接手一项依赖其他同事的工作，你会怎样拆分任务并估算时间？",
                    "拆分粒度", "识别依赖和不确定性", "协作与反馈节点"),
            new Template("反馈迭代", "讲一次你根据用户或同事的反馈改变方案的经历，说明它对「%s」工作有什么启发。",
                    "交代反馈及判断", "具体调整", "验证调整后的效果"),
            new Template("失败复盘", "分享一项与「%s」有关、结果没达到预期的工作。你会怎样复盘？",
                    "描述结果与目标差距", "由证据推断原因", "下次行动"),
            new Template("学习应用", "「%s」岗位要求一项你刚接触的技能。举例说明你如何学会类似技能并把它用到实际任务中。",
                    "明确学习目标", "实践方式", "验证技能能否独立应用"),
            new Template("知识迁移", "介绍一项你熟悉的方法或工具。它在「%s」工作中适合用在哪里？什么情况下你会换一种做法？",
                    "说明方法及应用条件", "指出局限", "提出可行替代"),
            new Template("跨团队协作", "举一个你和不同背景的同事协作的例子。应聘「%s」时，你会怎样描述自己的沟通和交付工作？",
                    "以实例说明协作", "推动沟通和决策", "把结果说清楚"));

    private static final List<Template> SCENARIO = List.of(
            new Template("进度与质量", "假设你担任「%s」，交付临近时发现一个影响部分用户的问题。你会如何决策和同步？",
                    "识别影响范围", "给出止损、修复或延期的判断依据", "同步风险与责任"),
            new Template("优先级判断", "作为「%s」，你同时收到两项紧急任务，资源只够完成一项。你怎样决定优先级？",
                    "比较影响与时限", "与相关人员对齐", "交代另一项的后续处理"),
            new Template("协作分歧", "你担任「%s」时，与你合作的同事对验收标准有分歧。你会怎样推动双方达成可执行的方案？",
                    "理解分歧", "明确共同目标和衡量方式", "给出解决步骤"),
            new Template("资源约束", "如果你在「%s」岗位需要在一周内交付第一个版本，你会怎样决定哪些能力先做、哪些延后？",
                    "基于目标确定范围", "给出验收和排序依据", "安排后续迭代"),
            new Template("业务变化", "假如你以「%s」身份交付的方案遇到需求变化，第一个版本的部分工作需要返工。你会怎么推进？",
                    "核对变化及影响", "评估已有产出", "调整计划并说明代价"));

    List<Question> draw(String title, int count, List<Question> jobQuestions, Set<String> recent) {
        var selected = new ArrayList<Question>();
        var prompts = new HashSet<String>();
        add(selected, prompts, templates(WARMUP, Phase.WARMUP, title), 1, recent);
        int scenarios = count == 8 ? 2 : 1;
        var closing = new ArrayList<Question>();
        add(closing, prompts, templates(SCENARIO, Phase.SCENARIO, title), scenarios, recent);
        var core = templates(CORE, Phase.CORE, title);
        core.addAll(jobQuestions);
        add(selected, prompts, core, count - scenarios - 1, recent);
        selected.addAll(closing);
        return List.copyOf(selected);
    }

    private static ArrayList<Question> templates(List<Template> bank, Phase phase, String title) {
        var result = new ArrayList<Question>();
        for (int index = 0; index < bank.size(); index++) {
            result.add(bank.get(index).forRole(phase.name().toLowerCase(Locale.ROOT) + "-" + (index + 1), phase, title));
        }
        return result;
    }

    private static void add(List<Question> selected, Set<String> prompts, List<Question> pool, int count, Set<String> recent) {
        Collections.shuffle(pool);
        pool.sort(Comparator.comparing((Question question) -> recent.contains(question.id()))
                .thenComparing(question -> question.sourceName().equals("内置模拟题库")));
        pool.stream().filter(question -> prompts.add(normalize(question.prompt())))
                .limit(count).forEach(selected::add);
    }

    static String normalize(String prompt) {
        return prompt.replaceAll("[\\p{P}\\p{Z}\\s]", "").toLowerCase(Locale.ROOT);
    }
}
