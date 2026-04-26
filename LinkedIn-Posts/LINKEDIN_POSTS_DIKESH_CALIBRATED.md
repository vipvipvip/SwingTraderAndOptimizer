# LinkedIn Posts - Dikesh Chokshi: CTO Perspective on AI, Teams & Enterprise Tech

## Post 1: The CTO Role Is Fundamentally Changing—Here's Why and What to Do About It
**Category: Technology Leadership | Word count: 420**

---

Over 25 years, I've held the CTO title at Censeo, Quaeris, EDA, and advisory roles at several others. If I'm being honest, the job description has shifted dramatically in the last 18 months.

Five years ago, a CTO needed to:
- Understand architecture patterns and scalability
- Lead engineering teams
- Make buy-vs-build decisions
- Manage technical debt and infrastructure

Today, those are still table stakes. But they're not enough anymore. The new CTO challenge is this: **How do we leverage AI to accelerate execution while maintaining the technical judgment that prevents disasters?**

Here's what changed.

**The Old Math:**
- Need a feature? Hire 2-3 engineers, 3-6 months to deliver
- Technical debt? Plan a quarter-long refactor with your team
- Scaling problem? Rearchitect and migrate (AWS migration at Quaeris took 4 months of careful coordination)
- Vendor negotiation? You had time for RFPs and deliberation

**The New Math:**
- Need a feature? One senior engineer, 2-4 weeks, with AI coding assistance
- Technical debt? Regenerate it smarter, test it thoroughly, rewrite it cleaner
- Scaling problem? Build it right the first time because rebuilding is cheap
- Vendor negotiation? Data-driven comparison speeds decisions dramatically

**What This Means for CTOs:**

1. **Your team structure needs to change.** I've always managed teams of 5-40 engineers. Now I'm asking: do we need that many? The answer is: depends on what you're optimizing for. If it's velocity, fewer senior people with AI assistance beats many mid-level people. If it's knowledge distribution and risk mitigation, you need the team but organized differently.

2. **Hiring criteria shift.** You can't hire on "coding speed" anymore—AI commoditized that. You hire on judgment, architecture thinking, and domain expertise. The engineer who can say "we don't need that feature" is worth more than the engineer who can code it fast.

3. **Your time allocation changes.** Less time reviewing code, more time on decisions: Are we building the right thing? Can we operate it? What happens if this assumption is wrong? These are the conversations that matter now.

4. **Risk concentration increases.** When you had 10 engineers, 8 of them were implementing specs you didn't set. Now with fewer people and AI doing implementation, more decisions concentrate at the top. You need very good judgment, very fast.

5. **Technical depth becomes your moat.** AI can implement any specification. It can't decide what the specification should be. The CTOs winning right now are the ones with deep domain expertise—they know what matters in their business, what can be automated, what still requires human judgment.

**What I'm Watching:**

CTOs who are thriving with AI:
- Started with strong architecture discipline
- Already had distributed teams (so they understand asynchronous, documented decision-making)
- Have domain expertise (they know their business deeply)
- Built verification into their culture (they don't trust code, they test it)

CTOs who are struggling:
- Trying to maintain the old structure while adding AI (you can't—it breaks)
- Treating AI as "cheaper implementation" without changing how they think about problems
- Losing technical credibility because they're now removed from implementation
- Not building the verification discipline fast enough

**For Other Technology Leaders:**

If you're a CTO, VP of Engineering, or technical executive evaluating AI for your team, here's what I'd ask:
1. Do we have architecture discipline right now? (AI amplifies that, good or bad)
2. What are we actually optimizing for? (Speed? Reliability? Team size? Cost?)
3. Who on our team has the deepest domain expertise? (Protect and empower them—they're now your strategic asset)
4. Are we prepared to verify more thoroughly? (Code that works ≠ code that's correct)

This isn't a technology shift. It's an organizational and strategy shift. The enterprises that recognize that will keep their technical credibility and competitive advantage. The ones that don't will ship fast and fail slow.

---

## Post 2: Why Cost Optimization is More Strategic Than You Think
**Category: Finance & Operations | Word count: 400**

---

At Mercer, I negotiated a CDN contract that saved $500K annually. At EDA, we reduced development costs by 75% through offshore hiring and infrastructure optimization.

These weren't cost-cutting exercises. They were strategic moves that changed what we could build and how fast.

**The Economics Most CTOs Miss:**

When I led Censeo as co-founder, we bootstrapped. Every dollar we didn't spend on overhead was a dollar we could invest in features. But I didn't understand the strategic implication fully until later: cost discipline isn't about being cheap. It's about capital efficiency and optionality.

Here's what changed my thinking:

At Quaeris, we were paying $180K/month for cloud infrastructure. The business wasn't at that scale yet. We had options:
1. Accept the cost and let it drive business development (we need to sell fast to justify it)
2. Optimize the infrastructure (which would've taken a senior engineer 3 months)
3. Rearchitect to reduce usage (Kubernetes instead of standalone VMs—this is what we did)

Option 3 cost us $60K in engineering time and effort. It reduced monthly cloud spend to $45K. Payback in 2.5 months. But the strategic win was different: we now had margin. We could take risks, hire faster, invest in technical debt without desperation.

**What This Tells Me About Enterprise Technology:**

The companies with the most technical freedom are the ones with cost discipline. They have breathing room. They can invest in the right thing instead of the urgent thing.

Most enterprises struggle the opposite way: they haven't optimized infrastructure, they haven't negotiated vendor contracts properly, they've hired more people than they need because they didn't have discipline. Then when a down market hits, they panic, cut costs without strategy, and destroy the organization.

**How AI Changes This:**

AI-assisted development means you can do more with less. But only if you have discipline around:
1. **Infrastructure costs** (AI makes it cheaper to generate code, but code quality determines infrastructure efficiency)
2. **Team size** (you genuinely can do more with fewer people, but only if they're the right people)
3. **Vendor contracts** (suddenly you need fewer engineers, which changes your leverage with cloud providers—renegotiate)

I've managed distributed teams in India, Romania, Ukraine, and Colombia. Offshore development isn't just about hourly rates anymore. With AI, it's about access to quality engineers who can think, not just code. The calculus completely changes.

**The Strategic Lesson:**

Every dollar you optimize in operations is a dollar you can invest in innovation. Every percentage point you improve in infrastructure efficiency is margin that survives downturns. Every hire you don't make is a decision you didn't have to coordinate across.

This is how you build optionality. And optionality is what separates companies that can navigate change from companies that break under it.

**For CFOs and Finance Leaders:**

When the CTO comes to you asking for infrastructure investment or team expansion, the question isn't "can we afford it?" It's "have we optimized what we already have?" If the answer is no, ask them to do that first. You'll find they can deliver the same results with 60-70% of what they asked for.

For CTOs:
If you want credibility with finance and the board, learn to optimize. Demonstrate that you can do more with less. That's not being cheap—that's being strategic. And it's the skill that keeps you in the room for board-level decisions.

---

## Post 3: Building Distributed Teams That Actually Work—25 Years of Pattern Recognition
**Category: Organizational Leadership | Word count: 390**

---

I've managed teams across 5 continents: India, Romania, Ukraine, Colombia, and onshore.

Every model has different economics. Every model has different failure modes. And the pattern I see now—with AI in the mix—is that geography matters less than discipline.

**The Journey:**

At Censeo (2000-2011), I had 5-20 developers. Started onshore, expanded offshore to India and Romania because we had to—startup economics. We learned quickly: timezone differences are real, timezone discipline is crucial, documentation becomes non-negotiable.

At Mercer (2011-2014), I led larger teams, coordinated offshore operations across geographies. The pattern was: onshore architects and SMEs, offshore implementation at scale.

At Quaeris (2021-2023), I hired contractors in Ukraine and Colombia alongside FTE engineers in India. The calculus was different then: we weren't just looking for cost, we were looking for specific skills in specific time zones.

Now, with AI:

**The Old Offshore Model:**
- Architects/seniors onshore
- Implementation offshore (cheaper, 40% of US cost)
- Coordination overhead: 3x bandwidth spent on communication
- Risk: knowledge concentrated onshore, offshore team is interchangeable

**The New Model (Emerging):**
- Smaller onshore core (architects, decision-makers, domain experts)
- Offshore engineers pair with AI (implementation is fast, margins are better)
- Coordination: *still* required, maybe more because decisions are faster
- Risk: different—now it's about verification and testing, not hand-holding

**What Actually Works:**

1. **Ruthless documentation.** This was always true, but now it's existential. If your team is distributed and moves fast with AI, everything they decide needs to be written. Not comments in code—actual decision documents.

2. **Async decision-making.** If you're coordinating across time zones, synchronous meetings are death. You need a culture where decisions happen in writing, async, with clear escalation paths.

3. **Owned domains.** Each team owns a vertical. Ownership prevents the "we're waiting on that other team" syndrome. With AI acceleration, the worst thing you can do is create artificial dependencies.

4. **Verification discipline.** The faster you move, the more verification you need. This isn't negotiable. I've seen teams that moved fast and failed catastrophically because they skipped testing.

5. **Quality hiring.** You can't hire junior people for distributed offshore teams anymore. They need to think independently because you can't hand-hold across time zones. Hire mid-level and above, even offshore.

**The Economics Today:**

- US engineer: $150-200K salary
- India senior engineer: $40-50K salary (still serious talent)
- Ukraine senior engineer: $50-70K salary
- Colombia senior engineer: $50-65K salary

With AI, the productivity gap between these tiers is smaller. A great India-based engineer with Claude can probably outproduce a mediocre US engineer without it.

But coordination and decision-making still happen onshore, or with someone in the office. You can't distribute judgment as easily as you can distribute implementation.

**For Organizations Building Distributed Teams:**

1. Don't hire offshore to save money. Hire offshore to access talent and scale. If cost is your primary metric, you'll hire the wrong people.

2. Invest in documentation and async communication infrastructure. This is as important as paying salaries.

3. Hire senior people offshore. Junior people need mentoring. You can't mentor async.

4. Maintain a onshore core that knows the business deeply. Not everyone, but enough.

5. Build in verification at every step. The faster you move, the more testing you need.

The companies I've seen fail with distributed teams did it because they treated offshore as "cheaper labor" not "access to talent." The companies that succeeded treated it as geographic arbitrage with discipline.

AI changes the equations but doesn't change the discipline required.

---

## Post 4: The Vendor Management Skill Nobody Talks About—But Should
**Category: Enterprise Strategy | Word count: 370**

---

I've negotiated contracts with Azure, AWS, Hubspot, Fivetran, Snowflake, and smaller vendors. The pattern is always the same: most engineers and technical leaders leave millions on the table because they don't negotiate.

**The $500K Lesson:**

At Mercer, we had a CDN contract for delivering TalentSim globally. The vendor billed monthly based on usage. Each month: different costs, hard to predict.

Finance hated this. Operations hated this. I called the CDN provider and said: "Here's what we need. Give us a fixed-cost model that works for both of us."

The negotiation took 6 weeks. But the result: $500K in annual savings with predictable, fixed costs. Both of us were happy—we had certainty.

**Why This Matters for CTOs:**

When you're small, you take standard pricing. When you grow, you have leverage. Most CTOs don't recognize the moment when their leverage exists. They just keep paying the standard rate.

Here's what changed my thinking:

At Quaeris, we were spending $15K/month on various cloud and SaaS vendors. The business was at $X revenue. At one point, someone asked: "Why aren't we negotiating these contracts?"

We did:
- Azure: reduced by 25% with volume commitment
- Hubspot: reduced by 40% by committing to annual spend
- Fivetran: negotiated better pricing for data pipeline volume

Total savings: $3,600/year. For 30 minutes of conversation per vendor.

At EDA, we went further: created technical partnerships with Azure and Snowflake. Not for cost reduction, but for co-marketing, technical support, and strategic alignment. This costs nothing but positioning.

**The Pattern I See:**

Most companies negotiate IT services contracts (they have procurement teams). Very few negotiate technical vendor relationships (engineering teams don't think it's their job).

But the CTO should own this because:
1. You know which vendors are strategic vs. commodities
2. You know actual usage patterns (vendors often don't)
3. You have credibility with vendors (if you say you'll use 3x more capacity, they believe you)
4. You can propose alternatives (maybe you don't need this vendor if you architect differently)

**What Most Vendors Will Do:**

1. **Volume discounts.** If you commit to higher spend, they'll reduce rate
2. **Longer terms for better pricing.** 3-year commitment gets better pricing than monthly
3. **Technical partnerships.** If you're strategic to their story, they'll invest in supporting you
4. **Alternative pricing models.** Most have standard models, but custom arrangements are possible
5. **Included services.** Training, consulting, premium support—these are often negotiable

**What I'd Advise CTOs:**

1. Audit all your vendors quarterly. Know who you pay and why.

2. For top 5 vendors: negotiate actively every year. Even if last year was good, there's room.

3. Propose alternatives: "If you reduce pricing by 20%, we'll expand usage by 50%." Vendors understand that math.

4. For strategic vendors: propose partnerships, not just pricing. This is worth more long-term.

5. Get procurement involved for contracts, but don't let them own the relationship. You need to stay connected technically.

This isn't complicated. But most technical leaders don't do it because they see it as admin work. It's not—it's capital efficiency. And capital efficiency is strategic.

---

## Post 5: The Architecture Decision That Pays Dividends for Years
**Category: Systems Architecture | Word count: 380**

---

At EDA, I migrated the survey application from standalone VMs to Azure Container Instances. At Quaeris, I moved from monolithic to Kubernetes. At Censeo, we built microservices before it was trendy.

Each decision cost $50K-$150K in engineering effort upfront. Each paid back in 12-24 months. The third year was pure margin.

**Why This Matters:**

An architecture decision isn't just technical. It's financial. It's organizational. It determines:
- How many engineers you need to operate the system
- How fast you can move to new features
- What risks you're exposed to
- How much you spend on infrastructure

Get the architecture right, and the business compounds its advantage. Get it wrong, and you're paying the tax for years.

**The Pattern Across Companies:**

At Censeo (2000-2011), we built on .NET and SQL Server. Single-tenant architecture. Each customer got their own instance. This was expensive to maintain (many databases) but easier to isolate and scale.

At Mercer (post-acquisition), we transitioned to multi-tenant. Different economics, different problems (data isolation complexity), but better unit economics.

At Quaeris, we moved from monolithic APIs to Kubernetes. Why? Because the product was growing, feature development was slowing down due to deployment risk, and teams were stepping on each other's toes. Kubernetes removed those constraints.

At EDA, we moved from VMs to Container Instances. Not Kubernetes (overhead we didn't need), but containers gave us orchestration, scalability, and reduced overhead. Cut operations overhead by 30%.

**The Decision Framework:**

When evaluating architecture changes, I ask:
1. **What's the constraint today?** (Scalability? Deployment risk? Operational overhead? Team coordination?)
2. **How much will fixing it cost?** (Engineering effort, migration risk, maintenance cost going forward)
3. **What's the payback period?** (When does the benefit exceed the cost?)
4. **What new risks does it introduce?** (Complexity? Operational burden? Vendor lock-in?)
5. **Can we incrementally migrate or is it all-or-nothing?** (Incremental is lower risk)

If payback is <24 months and new risks are manageable: do it.

If payback is >36 months or new risks are high: defer or architect differently.

**What I See Going Wrong:**

1. **Architecture as cargo cult.** Teams adopt Kubernetes because it's trendy, not because they need it. Now they're maintaining infrastructure they don't need.

2. **Ignoring operational cost.** A more complex architecture requires more operational expertise. If you don't have it, the cost goes up.

3. **Not measuring before/after.** You don't know if the architecture change actually helped because you didn't baseline.

4. **Doing it wrong.** Moving to microservices without understanding distributed systems. Moving to cloud without understanding cloud pricing. The new architecture makes things worse.

5. **Not communicating the why.** Teams implement the new architecture but don't understand why. When problems surface, they don't have the judgment to make good decisions.

**For Technology Leaders:**

Architecture decisions are capital allocation decisions. Treat them like business investments:
- Define the constraint clearly
- Estimate the benefit and cost
- Set a payback deadline
- Measure whether you achieved the benefit
- Adjust if you didn't

This discipline prevents architectural whiplash (redesigning every 18 months) and ensures architectural decisions create actual business value.

The enterprises winning now have 3-5 year-old architecture that's still working well because it was designed properly and measured carefully. The ones struggling are redesigning constantly because they chase trends instead of constraints.

---

## Post 6: What I Learned About AI From Building With It—Not Using It
**Category: AI & Strategy | Word count: 410**

---

I've been in tech since 1990. I've seen: the PC revolution, internet commerce, cloud computing, mobile, and now AI.

Each wave, the mistake is the same: confusing the tool with the transformation.

**The Pattern:**

- Cloud era (2010s): Everyone built cloud apps. Most should've just migrated existing architecture. It didn't fundamentally change what you build, just where you build it.

- Mobile era (2000s): Everyone needed a mobile app. Most should've asked: "Do our customers actually want a mobile app or do they want responsive design?"

- AI era (2020s): Everyone needs AI. But most should've asked: "Where does AI actually create value vs. where are we using it as complexity camouflage?"

**What I Discovered Building with Claude:**

About 6 weeks ago, I started experimenting with Claude for building a complete system: Python optimizer, PHP backend, Svelte frontend, infrastructure. Real code. Real system. Not a demo.

Here's what I learned:

**Claude is exceptional at:**
- Boilerplate and integration code (80% of what gets written)
- Code you're confident about (clear specifications, well-defined problems)
- Code you can verify thoroughly (no domain-specific subtleties)
- Documentation and explanation (it's articulate)
- Refactoring (taking working code and making it better)

**Claude is weak at:**
- Domain logic where judgment matters (Should the position size be 10% or 15% of capital? There's no code answer.)
- Problems without clear specs (ambiguous requirements)
- Problems that compound (make one wrong decision, it affects 5 other decisions)
- Testing (it can write tests but can't think of edge cases you haven't articulated)

**What This Means:**

Claude didn't replace me as an engineer. It made me a better architect because I had to specify everything precisely. It couldn't decide whether to use a microservices or monolithic architecture—I had to decide. It couldn't determine if the algorithm was correct—I had to verify.

So here's the honest assessment:

**AI is a force multiplier for senior engineers, not a replacement.**

A senior engineer with Claude can do 2-3x the work. A mid-level engineer can probably do 1.5x the work. A junior engineer with Claude might do less than 1x because they're fixing Claude's mistakes without understanding why.

This has serious organizational implications.

**For Organizations:**

If you're thinking "AI lets us hire fewer engineers," you're right. But you need different engineers. You need people who can:
- Specify problems precisely
- Review code critically (not just trust AI)
- Verify correctness (can't delegate to testing)
- Make architecture decisions (the high-leverage work)

The enterprises betting on AI while cutting senior staff are making a mistake. The enterprises hiring senior staff and giving them AI tools are winning.

**For Technical Leaders:**

Three questions:

1. **Is our architecture sound?** (AI amplifies good architecture, punishes bad ones)
2. **Do we have people who can specify clearly?** (That's the new constraint)
3. **Have we built verification discipline?** (Faster code requires faster testing)

If you can answer yes to all three, use AI aggressively. If not, address those first.

**My Current Thinking:**

AI is real. It's transformative. But it's not magic. It's a tool that makes leverage more powerful—good decisions compound, bad ones compound faster.

The CTOs and organizations winning with AI right now aren't the ones using it most aggressively. They're the ones using it most intentionally.

---

## Post 7: The CTO Transition—From Hands-On Builder to Strategic Leader
**Category: Career & Leadership | Word count: 400**

---

At Censeo, I built the product. I wrote code. I knew every feature, every database schema, every performance characteristic.

As the company grew, I had to let that go.

By 2008, I was CTO but I wasn't building anymore. I was deciding what to build, reviewing architecture, managing teams, negotiating with customers about technical complexity.

It was a painful transition. And I see a lot of technical leaders struggling with the same thing right now.

**The Tension:**

Deep technical knowledge is what made you effective as an engineer. You solved complex problems. You understood the codebase. You could move fast.

But as you become a leader, that same knowledge becomes a liability if you can't let it go. You second-guess your team's code. You want to rewrite things. You can't delegate because you see how it "should" be done.

**What Changed for Me:**

Early in my career (Censeo), I tried to be both. Builder and leader. It didn't work at scale.

By Mercer, I realized: **My job is to make decisions no one else can make.** 

- Architects can design systems. I decide which architecture matters for the business.
- Engineers can write code. I decide what problem we're actually solving.
- Product managers can prioritize features. I decide what's technically feasible and what's not.
- Teams can execute. I decide how resources are allocated and risks are managed.

**The New Transition (AI Changes This):**

With AI coding assistants, I see a different path emerging:

Rather than "leader who used to code," it's now "architect who leverages AI for execution."

A CTO with Claude can:
- Spend 60% of time on architecture and strategy
- Spend 30% on code review and verification
- Spend 10% writing actual code when it matters

This is different from 10 years ago when a CTO doing 10% code review meant they were disconnected.

**What This Requires:**

1. **Let go of perfectionism.** Code written by AI-assisted engineers might not be exactly how you'd write it. That's okay if it's correct and maintainable.

2. **Focus on the high-leverage decisions.** Architecture, strategy, talent, capital allocation. Not implementation details.

3. **Stay technically credible.** You don't do all the coding, but you understand the codebase deeply. You can review architecture, spot problems, ask good questions.

4. **Build judgment infrastructure.** Surround yourself with people who can challenge your thinking. An isolated CTO makes bad decisions.

5. **Know what you don't know.** Hire people smarter than you in specific domains. Your job is orchestrating their expertise, not duplicating it.

**The Real Shift:**

I've moved from "I know how to build this system" to "I know how to organize people to build systems well."

That shift is uncomfortable. It means you're less valuable if someone steals the code (because the code isn't your competitive advantage anymore—the thinking is). It means you're more valuable if your team is strong (because execution depends on them, not you).

**For Engineers Considering the CTO Path:**

Ask yourself: Can I be fulfilled making decisions if I'm not implementing them? Can I find satisfaction in a team's success rather than my individual work?

If yes: become a technical leader. The leverage is enormous.

If no: become a principal engineer or architect. Stay deep in the technical work. Both paths are valuable.

**For Current CTOs:**

You're in a transition moment. AI is making implementation cheaper and faster. That means architecture and judgment are more valuable than ever.

Don't try to stay hands-on if you're responsible for decisions at scale. It doesn't work. Evolve into the role you actually need to play.

But keep enough technical currency that you maintain credibility. Nothing undermines a CTO faster than being out of touch technically.

---

*Follow for more on technology strategy, enterprise architecture, and the future of technical leadership. Open to consulting, advisory, and CTO/VP Engineering conversations.*

