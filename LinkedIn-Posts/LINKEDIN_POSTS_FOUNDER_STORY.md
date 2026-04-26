# LinkedIn Posts - The Founder Story: Building, Scaling, and Exiting Censeo

## Post 1: The 11-Year Journey: What I Learned Building Censeo From Scratch
**Category: Entrepreneurship | Word count: 420**

---

I co-founded Censeo Corporation in 2000 with a simple idea: automate 360-degree multirater surveys and make leadership assessments scalable.

For 11 years, we built. We hired. We optimized. We scaled. Then in 2011, we sold to Mercer.

That journey taught me more about business, technology, and human judgment than any MBA or Fortune 500 job ever could.

**The Early Days (2000-2003):**

Two of us. .NET and SQL Server. Building survey software in a market where HR executives still used Excel and email.

The first hard lesson: **building a product is 10% of the work. Selling it is 90%.**

We'd build features customers asked for. Then we'd call to ask why they hadn't bought. Answer: wrong person, wrong budget cycle, wrong value proposition. We were solving a problem nobody knew they had.

**The Growth Phase (2003-2008):**

We figured out the go-to-market. Small HR departments loved us. HR Business Partners used us. We hired our first real salespeople. Revenue grew. We needed engineers—lots of them. Hired in India and Romania because US engineers were expensive.

The second hard lesson: **scaling engineering is not about hiring more engineers. It's about building systems that junior engineers can work within.**

We created platform standards. Database patterns. API contracts. Code style guides. At some point, we had 15-20 engineers. The code quality didn't collapse because we had architecture discipline. New engineers could contribute meaningfully in week 2, not week 4.

**The Maturity Phase (2008-2010):**

We built products: 360 MultiRater Survey, TalentSim, KnowledgeTrack, Employee Opinion Survey. TalentSim won Product of the Year from Human Resource Executive Magazine.

The third hard lesson: **profitability is about unit economics, not revenue.**

We could've grown faster by taking VC money and burning cash. Instead, we grew profitably. That meant scrutinizing cost per customer, CAC, LTV. Every hire had to pay for itself. Every feature had to generate revenue.

This discipline shaped everything: we preferred to sell to 500 customers at $50K each rather than 5,000 at $5K. Smaller customer base, more revenue, higher margins, profitable.

**The Exit (2010-2011):**

Mercer, a large consulting firm, acquired us. They had distribution. We had product. It made strategic sense.

The fourth hard lesson: **exits are emotionally complicated, even when they're financially good.**

You spend 11 years building something. You know every line of code. Every customer relationship. Every team member. Then you hand it off. The product lives on, but it's not yours anymore. That's weird.

**What I'd Do Differently:**

1. **Hire more senior people earlier.** I hired bright junior people and trained them up. That worked but cost time. Hiring experienced people from day one accelerates everything.

2. **Build unit economics discipline earlier.** By 2008, we had it. By 2004, we should've had it.

3. **Delegate faster.** I was involved in everything early on. That's necessary. But I held on too long. By 2008, I should've been fully out of engineering and focused on strategy.

4. **Be more intentional about exit planning.** We exited well, but we could've extracted more value with better planning 2-3 years in advance.

**What Stayed True for 11 Years:**

- Build products people actually need (took us 18 months to figure out what we were selling, but once we did, the mission was clear)
- Hire people smarter than you (our engineers and salespeople were almost always smarter than me in their domains)
- Optimize for profitability, not growth (margins create freedom)
- Build architecture discipline early (saved us from total chaos as we scaled)

**For Founders Reading This:**

Building a company from scratch is a superpower. You learn things you can't learn anywhere else:
- How to make tradeoff decisions with real consequences
- How to hire and fire and manage people
- How to understand customers directly
- How to think about capital and ROI
- How to balance ambition with reality

If you're considering founding or you're early in a startup: the 11-year marathon is worth it, even if you don't hit the home run. You'll understand business in a way that changes how you operate forever.

For me, that 11-year journey at Censeo is why I can be effective as a CTO at EDA, Quaeris, and elsewhere. I've been on all sides of the table: founder, operator, acquirer, advisor.

---

## Post 2: The First Three Customers—And Why They Matter More Than You Think
**Category: Entrepreneurship & Go-to-Market | Word count: 380**

---

Censeo's first paying customer was a mid-sized manufacturing company with an HR department of 3 people.

They paid us $15K/year. For that, we customized our product heavily. We flew out to meet them. We responded to every question at 9 PM on Sundays.

Financially, we lost money on that customer. Operationally, we gained everything.

**Why That Mattered:**

Those first three customers weren't about revenue. They were about:
- Validating that someone would pay for what we built
- Understanding what we actually built vs. what we thought we built
- Building references for the next 10 customers
- Learning what customers valued (not what we assumed they valued)

**The Specific Lessons:**

Customer 1 (Manufacturing): Showed us that companies cared about data security and compliance. We were thinking about features; they were thinking about risk. We redesigned the product around audit trails.

Customer 2 (Financial Services): Showed us that large organizations have bureaucracy. Purchase orders. Procurement processes. IT department approvals. We thought 30 days to close a sale was normal; they closed in 6 months. But once they closed, they paid on time and renewed.

Customer 3 (Professional Services): Showed us that different verticals have different problems. Professional services cared about billability and time tracking alongside 360 reviews. Manufacturing didn't care about that at all.

By customer 10, we stopped customizing heavily. We had enough data to say: "Here's what our product does. You can either use it or you can't." That's when profitability started.

**The Hard Realization:**

Most founders want to avoid "customer development" because it feels slow. You're not shipping features fast. You're having 10 conversations that produce 5 different requirements.

But skipping customer development is how you build the wrong product. You spend $100K building what you *think* customers need, then discover they need something different.

The companies that win are the ones who validate assumptions with real customers before scaling.

**For Entrepreneurs:**

1. **Get to paying customers fast.** Free users give feedback about features. Paying customers tell you about value.

2. **Listen to your first 10 customers obsessively.** They'll teach you everything.

3. **Be willing to customize heavily early.** Once you understand the pattern, you can productize.

4. **Know when to say no.** By customer 5, we could say "our product does X, not Y." That separates viable businesses from custom-services businesses.

5. **Pick customers that align with your long-term vision.** If you want to sell to enterprises, don't get locked into SMB customer patterns.

The difference between Censeo's success and failure was that first phase of listening deeply to customers. It delayed our growth by 18 months. It also made sure we were building something people actually wanted.

That 18-month delay saved us from 5+ years of building the wrong thing.

---

## Post 3: Scaling From 5 Engineers to 20 Without Losing Your Mind
**Category: Engineering Leadership | Word count: 390**

---

At Censeo, the hardest transition happened around year 4-5, when we went from 5 engineers to 15-20.

We had revenue. We could afford to hire. But suddenly everything broke.

Code reviews took forever. Shipping slowed down. People stepped on each other's toes. Junior engineers were confused about how to contribute. Senior engineers were frustrated because junior people didn't understand the system.

**What We Learned to Do:**

1. **Define architecture in writing, not in people's heads.**

Before: I was the architect. Everyone knew how things should work because I explained it to them. When I was in a meeting, things still got built correctly.

After: We wrote architecture docs. Here's how data flows. Here's the API contract. Here's what each team owns. Junior engineers could read it and contribute meaningfully.

This felt inefficient at the time ("Why write docs when I can just explain it?"). It was actually hugely efficient because now knowledge was scalable.

2. **Create platform standards and enforce them.**

Code style guide. Database naming conventions. API patterns. PR review checklist. People hated these at first ("Why does it matter if I name my variable X instead of Y?"). But once they existed, on-boarding went from 4 weeks to 2 weeks. Code quality stayed consistent.

3. **Build layers of review, not bottlenecks.**

Early on, I reviewed all code. That didn't scale. So we created a system where:
- Junior engineers paired with senior engineers
- Senior engineers reviewed code in their domain
- I reviewed architecture-level changes, not every PR

This scaled much better. But it required senior engineers who could review code AND mentor.

4. **Hire for specific gaps, not generic engineers.**

At 5 engineers, you hire the smartest person you can find. At 15, you hire for specific gaps: "We need someone strong in database optimization" or "We need a leader for the mobile team."

This requires clarity about what you're building and where you're weak.

5. **Separate technical leadership from people management.**

Around year 5, I realized I was both: architect (technical) and executive (people). That's too much for one person at scale.

We created a VP Engineering role (people management, hiring, culture) separate from the architect role (technical direction). This was one of the best decisions we made.

**What Almost Killed Us:**

Hiring fast without on-boarding infrastructure. We hired 5 engineers in 6 months without updating our docs, processes, or management structure. For 3 months, we were absolute chaos. People built things that conflicted. We merged code that broke things.

We had to pause hiring, fix the process, then scale again. It cost us 2-3 months but prevented 12 months of chaos.

**For Engineering Leaders:**

The phase from 5 to 20 engineers is a critical inflection point. Your operations that work at 5 don't work at 20. But the new operations feel bureaucratic when you have 5.

Don't wait. When you're at 8-10, start building the infrastructure you'll need at 20. Docs. Standards. Processes. It feels like overhead, but it's actually the difference between managed growth and chaos.

---

## Post 4: The Exit—What Nobody Tells You About Selling Your Company
**Category: Entrepreneurship & Exit Strategy | Word count: 400**

---

In 2011, we sold Censeo to Mercer. On the surface, it was a great outcome: we'd built something valuable, customers were happy, it sold.

The emotional and practical reality was more complicated.

**The Process:**

About 18 months before the actual sale, I started thinking about exit options. Not because I was desperate to sell, but because planning gives you options.

Mercer approached us because they had distribution channels and we had a product. It was strategic for both of us. But we also talked to other buyers. We considered staying independent. We considered raising growth capital to build bigger.

The conversations took 6-9 months. We got an LOI (letter of intent). Then 3 months of due diligence. Lawyers. Accountants. Mercer's team basically living in our office.

**The Hard Parts:**

1. **Your team starts leaving.** Once people know you're being acquired, some get nervous about the future. Some get excited about what comes next. Some start looking elsewhere. We lost 2 good people during the process, which hurt.

2. **You can't control the narrative.** We knew the deal was happening, but couldn't tell the team until much later. Rumors spread. People make bad assumptions.

3. **The money is less than you expect.** After taxes, after retention agreements (you have to stay for 18 months), after earnouts (pay if we hit targets), the actual cash is maybe 40-50% of the headline number.

4. **Your product becomes their product.** Mercer had different priorities. Some of our product visions were shelved. Some features we built became 10x more important. It's hard to watch decisions made differently.

5. **The emotional loss is real.** I'd been thinking about this product every day for 11 years. Now it's someone else's. That's... weird.

**What Went Well:**

- Mercer was respectful and professional. Not all acquirers are.
- The retention package kept key people in place during transition.
- Customers were happy about the combination. We didn't lose anyone.
- The financial outcome was solid (even after taxes and adjustments).
- I got to stay involved for 18 months helping the transition, then move on to new challenges.

**The Lessons for Founders:**

1. **Plan your exit 2-3 years in advance.** Don't wake up one day and decide you want to sell. Think about it earlier and shape the company accordingly.

2. **Understand acquirer incentives.** Mercer wanted product, customer base, and team. They cared less about our specific feature roadmap. Align on this before the deal.

3. **Negotiate the retention structure carefully.** 18 months of having to stay is long if you want to leave. 6 months might be too short if they want continuity. Think through this.

4. **Get good legal representation.** Don't cheap out here. Your lawyer should find ways to protect you that you don't think of.

5. **Know your numbers.** We had clean financial records, good data, minimal surprises. That made due diligence fast and the deal closer to what we expected.

6. **Prepare your team early.** Once the deal closes, tell people immediately. Uncertainty is worse than news, even if the news is different.

**The Long View:**

11 years building. 2 years exiting. 10+ years thinking about it after.

The company I built mattered. The customers we served benefited. The team I built went on to do other great things. That's the real success metric, not the exit price.

The financial exit was good. But the real value was learning how to think like an entrepreneur. How to make decisions with real consequences. How to build teams and products.

That's what I brought to every job after: CTO at Mercer, advisor at Halestreet, CTO at Quaeris, CTO at EDA.

The exit was an ending and a beginning.

---

## Post 5: The Biggest Mistakes I Made Building Censeo (And How I'd Fix Them)
**Category: Lessons Learned | Word count: 370**

---

If I could go back to 2000 with what I know now, I'd make different calls. Most would've accelerated the company. Some would've prevented real pain.

**Mistake 1: Hiring slow, then too fast.**

Years 1-3: I was too cautious about hiring. We were profitable so I thought we had to stay lean. We should've hired a VP Sales in year 2 (we hired in year 4). That 2-year delay probably cost us $10M in lost revenue.

Years 4-5: I over-corrected. Hired 8 people in 6 months without infrastructure. Chaos for 3 months.

Better approach: Scale hiring intentionally with infrastructure. Don't wait for crisis. Plan 18 months ahead.

**Mistake 2: Not focusing on unit economics early.**

For the first 4 years, I cared about revenue. Are we $1M? Are we $5M? Wrong metrics.

I should've asked: What's our CAC (customer acquisition cost)? What's our LTV (lifetime value)? Are we selling to the right customers?

We eventually figured this out, but we wasted time and money on low-margin customers we should've never pursued.

**Mistake 3: Staying too hands-on in engineering.**

I was the architect until year 7. That made sense at 5 engineers. By year 7, I should've fully transitioned to strategy, leaving architecture to someone else.

I was bottleneck. Every hard technical decision had to come through me. Senior engineers got frustrated. Junior engineers couldn't level up because I wasn't delegating.

Better approach: By year 3-4, start building someone up to be the next architect. By year 5, they own it. You're advisor, not decision-maker.

**Mistake 4: Not investing in sales and marketing infrastructure.**

Early wins came from me doing customer presentations. That doesn't scale past 10 customers.

We should've built a repeatable sales process much earlier. Templates. Playbooks. Training materials. Instead, every deal was unique because we relied on relationships.

By year 6, we finally built a real sales organization. That 4-year delay cost us a lot.

**Mistake 5: Holding on too long.**

By year 9-10, I was asking: Is this still exciting? Do I want to do this for 5 more years?

The answer was: Probably not.

But I held on because the company was stable and profitable. I didn't want to fail. But I also didn't want to grow it anymore.

Better approach: By year 8, have a real conversation with co-founders about the future. If the answer is "we want different things," plan the exit. Don't let inertia keep you building something you're not excited about.

**The Meta-Lesson:**

Every founder makes mistakes. The successful ones recognize them, learn, adjust, and don't repeat them. The unsuccessful ones repeat the same mistakes and blame the market.

I made these five mistakes. I learned from them. That learning is why I'm effective in subsequent roles.

For founders: Track your mistakes. Share them with other founders. Don't pretend you're perfect.

---

## Post 6: From Founder to CTO—A Different Kind of Leadership
**Category: Leadership Transition | Word count: 360**

---

After Censeo sold in 2011, I had a choice: stay with Mercer for the transition, or move to something new.

I stayed. VP/Principal at Mercer. Then advisor. Then CTO roles at other companies.

The transition from founder to CTO was disorienting in ways I didn't expect.

**The Difference:**

As a founder, your success metric is: does the company survive and grow? You're responsible for everything.

As a CTO, your success metric is much narrower: is technology enabling the business? Are we scalable? Are we reliable? That's it.

This sounds simpler. It's actually harder because you have less control. You don't own sales. You don't own product vision. You don't own capital allocation.

**What I Had to Learn:**

1. **Influence without authority.** As a founder, I could make decisions unilaterally. As a CTO, I had to influence the CEO, CFO, board. I couldn't order them to prioritize technology; I had to convince them.

2. **Operating in someone else's vision.** At Censeo, it was my vision. At Mercer/Quaeris/EDA, it was the CEO's vision and my job was making technology serve that vision.

3. **Navigating existing culture.** As a founder, you build the culture. As a CTO joining an existing company, you have to work within it (or slowly change it).

4. **Different pressure.** As a founder, the pressure is existential (will the company survive?). As a CTO, the pressure is operational (can we ship on time? are we secure? are we scalable?). Different in kind.

**Why This Matters:**

Founders make great CTOs but they need to unlearn some habits.

- Founders want to optimize for profitability. CTOs need to optimize for business outcomes (which sometimes means spending money).
- Founders want to control everything. CTOs need to delegate and trust.
- Founders are impatient about slow decisions. CTOs need to navigate corporate decision-making.

**The Inverse:**

Some CTOs become founders and struggle because they're not used to:
- Making decisions alone (as CTO, you had consensus)
- Taking personal financial risk
- Doing work that's not technology

**My Advantage:**

Having been a founder first, when I became a CTO, I understood:
- Why the CEO made certain decisions
- What the board cared about
- How capital worked
- Why profit margins matter

I could speak the language of founders and boards, not just engineers. That credibility is why I had influence as a CTO.

**For Technologists Considering the CTO Path:**

If you've been an engineer-IC, becoming a CTO is a step function in responsibility. If you've been a founder, becoming a CTO is actually slightly simpler (you have more constraints, less risk).

Both paths work. But they're different enough that your experience shapes how effective you'll be in the role.

The best CTOs have been both: hands-on builders (so they understand engineering) and decision-makers (so they understand business).

---

*Follow for more on building companies, scaling teams, and the long journey from startup to enterprise technology. Open to mentoring founders and advising boards on technology strategy.*

