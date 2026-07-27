# LinkedIn Posts - The Founder Story: Building, Scaling, and Exiting Censeo

## Post 1: The 11-Year Journey: What I Learned Building Censeo From Scratch
**Category: Entrepreneurship | Word count: 420**

---

I co-founded Censeo Corporation in 2000 with a simple idea: automate 360-degree multirater surveys and make leadership assessments scalable.

For 11 years, we built. We hired. We optimized. We scaled. Then in 2011, we sold to Mercer.

That journey taught me more about business, technology, and human judgment than any MBA or Fortune 500 job ever could.

**The Early Days (2000-2003):**

Five of us. .NET and SQL Server. Building survey software in a market where HR executives still used Excel and email.

The first hard lesson: **building a product is 10% of the work. Selling it is 90%.**

We'd build features customers asked for. Then we'd call to ask why they hadn't bought. Answer: wrong person, wrong budget cycle, wrong value proposition. We were solving a problem nobody knew they had.

**The Growth Phase (2003-2008):**

We figured out the go-to-market. Small HR departments loved us. HR Business Partners used us. We hired our first real salespeople. Revenue grew. We needed engineers—lots of them. Hired in India and Romania because US engineers were expensive.

The second hard lesson: **scaling engineering is not about hiring more engineers. It's about building systems that junior engineers can work within.**

We created platform standards. Database patterns. API contracts. Code style guides. At some point, we had small team of engineers. The code quality didn't collapse because we had architecture discipline. New engineers could contribute meaningfully in week 2, not week 4.

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

For me, that 11-year journey at Censeo is why I can be effective as a CTO at EDA, Halestreet, and elsewhere. I've been on all sides of the table: founder, operator, acquirer, advisor.

---

## Post 2: The First Three Customers—And Why They Matter More Than You Think
**Category: Entrepreneurship & Go-to-Market | Word count: 380**

---

Censeo's first paying customer was a large bank who wanted us to build a 360 platform.

They paid us $88K for a consulting gig and we started development of the 360 platform. We customized our product heavily. We responded to every question even at 9 PM on Sundays.

Financially, we probably lost money on that customer. Operationally, we gained everything.

**Why That Mattered:**

Our first three customers weren't about revenue. They were about:
- Validating that someone would pay for what we built
- Understanding what we actually built vs. what we thought we built
- Building references for the next 10 customers
- Learning what customers valued (not what we assumed they valued)

**The Specific Lessons:**

Customer 1 (Bank): Showed us that companies cared about data security and compliance. We were thinking about features; they were thinking about risk. We redesigned the product around audit trails.

Customer 2 (Tech): Showed us that large organizations have bureaucracy. Purchase orders. Procurement processes. IT department approvals. We thought 30 days to close a sale was normal; they closed in 6 months. But once they closed, they paid on time and renewed.

Customer 3 (Professional Services): Showed us that different verticals have different problems. Professional services cared about billability and time tracking alongside 360 reviews. Banks didn't care about that at all.

By customer 10, we stopped customizing heavily. We had enough data to say: "Here's what our product does. You can either use it or you can't." That's when profitability started.

**The Hard Realization:**

Most founders want to avoid "customer development" because it feels slow. You're not shipping features fast. You're having 10 conversations that produce 5 different requirements.

But skipping customer development is how you build the wrong product. You spend $100K building what you *think* customers need, then discover they need something different. Except for the initial version of a basic 360 platform, all the features came clients' need. Reports where heavily customized, but never built as one off. Great pains were taken to make it a feature available to all clients.

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

## Post 3: Why Our Architecture Won While Competitors Failed
**Category: Technical Leadership | Word count: 390**

---

At Censeo, we had 3 developers and 20 total employees. Our competitors had 50+ engineers across multiple companies. Yet every single competitor eventually closed shop. We didn't.

The difference was architecture thinking.

**The Philosophy: "What If There Were a Million?"**

I always asked one question before writing code: "What if there were a million users/records/transactions?"

Even when building for 20K employees, the architecture was designed for a million. Future-ready, but not over-engineered. We didn't add features we didn't need yet. We just built the foundations to support them when they came.

This meant every decision—database schema, API design, data pipeline—was made with scale in mind. But we never built complexity until we actually needed it.

**The Technical Moat**

Most competitors bought off-the-shelf components and glued them together. We built what mattered in-house:

1. **Multi-threaded PDF generation.** We built our own PDF generator capable of instant, on-demand report delivery. Competitors couldn't do this—they generated reports in batches, which meant delayed delivery. Clients noticed. Clients switched to us.

2. **Small, focused stack.** No bloat. No third-party widgets that came with baggage. Just what we needed, built right. This kept the system lean and fast.

3. **Infrastructure discipline.** F5 switches, no single points of failure, strong vendor SLAs. We invested in physical hardware that wouldn't let us down. Competitors cut corners here and paid the price when their infrastructure failed under load.

4. **Sound software practices.** Rigorous testing by my co-founder. Code discipline. Architecture ownership that never wavered.

**Why Competitors Failed**

I learned about competitors' architectures over the years. Their problem was always the same: they couldn't scale their code. As they grew, their systems became brittle. Adding features broke other things. Scaling broke performance.

They'd hire more engineers hoping to brute-force their way through. It didn't work. Their architecture was the limit, not their people.

By the time clients reached out to us, it was because they'd already suffered with competitors' platforms. They'd experienced lag, crashes, unexpected failures. We didn't have those problems because we'd built for scale from day one.

**The Board-Level Lesson**

This is why Mercer wanted us. It wasn't just product or customers. It was knowing that our tech wouldn't become a liability as they scaled. Our incremental cost per client was near zero. Adding a thousand more customers didn't require adding engineers.

That's the moat. That's what separates companies that scale from companies that collapse under their own weight.

**For Technical Founders:**

Think like an architect, not a coder. "What if there were a million?" isn't about building for a million users today. It's about building foundations that won't crack when you get there. That's how you win.

---

## Post 4: The Exit—What Nobody Tells You About Selling Your Company
**Category: Entrepreneurship & Exit Strategy | Word count: 400**

---

In 2011, we sold Censeo to Mercer. On the surface, it was a great outcome: we'd built something valuable, customers were happy, it sold.

The emotional and practical reality was more complicated.

**The Timeline:**

- **Q4 2010:** Mercer approached us. They saw the value in our business model—a SaaS platform with near-zero incremental cost per customer. That's the real moat.
- **Q1 2011:** LOI signed. Serious negotiations began.
- **Spring 2011:** Due diligence and data room creation. Lots of lawyers, lots of documents.
- **October 31, 2011:** Deal closed.

About 10 months from first conversation to close. Not rushed, but not interminable either.

**What Mercer Actually Wanted:**

Not just the product. Not just the customers. It was the **business model**.

We'd proven something rare: revenue scaling without headcount scaling. Each new customer added almost no incremental cost. That's the moat. Mercer understood that and wanted to build their entire software strategy around it.

**The Non-Negotiable:**

Before we signed, I made one thing clear: all 20 employees stay, and we distribute $250K-$300K from the acquisition proceeds to non-founder employees.

Without that, there was no deal. This wasn't charity—it was acknowledging that these people had built this with me, and they deserved to share in the outcome.

Mercer agreed. That trust became the foundation for everything that followed.

**What Went Well:**

- All 20 employees stayed through the full 3-year retention. Nobody left.
- Customers were happy about the combination. We didn't lose anyone.
- Mercer was respectful and professional about integrating us.
- The financial outcome was solid.
- The culture held. The team stayed together and thrived.

**The Lessons for Founders:**

1. **Plan your exit 2-3 years in advance.** Don't wake up one day and decide you want to sell. Think about it earlier and shape the company accordingly.

2. **Understand acquirer incentives.** Mercer wanted product, customer base, and team. They cared less about our specific feature roadmap. Align on this before the deal.

3. **Negotiate the retention structure carefully.** 36 months of having to stay is long if you want to leave. 6 months might be too short if they want continuity. Think through this.

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

**Mistake 1: Hiring for strategy I hadn't committed to.**

Years 1-3: Staying lean made sense. We were profitable and bootstrapped. No need to hire just to hire.

But by Year 4, when the data clearly showed enterprise customers were more profitable, I should've hired enterprise-focused talent: reps trained on long sales cycles, relationship building, C-level conversations. Instead, I kept hiring generalists.

For years, I had sales reps trained to close SMBs mixed with enterprise ambitions. That mismatch cost us. By the time I finally prioritized enterprise hiring (years 5-6), I'd already spent years with the wrong team for the strategy.

Better approach: Once you know your strategy (enterprise in our case), hire specifically for it. Don't hire "anyone who can sell." Hire people calibrated to the segment you're actually pursuing.

**Mistake 2: Hedging instead of focusing — even when the data was clear.**

By Year 3-4, I had enough customer data to see the pattern: Enterprise customers were more profitable than SMBs. Longer contracts, higher ACV, better retention, no hand-holding. The economics were obvious.

But I didn't act on it decisively. I kept saying "we'll serve both." Kept hiring sales reps who could close SMBs. Kept building features for low-value customers.

The mistake wasn't tracking CAC/LTV obsessively from day one — we were profitable anyway. The mistake was seeing the signal and not acting. By Year 4, I should've said: "Enterprise only. Everything else is distraction."

Instead, I hedged for 2-3 more years. That cost us time and focus, even if revenue kept growing.

**Mistake 3: Not grooming someone to understand the architecture.**

I stayed hands-on in architecture all 11 years—that was right. It's why we beat competitors who couldn't scale their code. My COO shielded me from operations so I could focus on it.

But I never brought someone in to *learn* the architecture: the foundation, how features evolved, why decisions were made, how the architecture informed design.

The "why" behind how we built things lived only in my head. By Year 4-5, I should have invested time in grooming someone—not to replace me, but to understand the principles. After the exit to Mercer, they inherited the code but not the reasoning.

That knowledge walked out the door with me, and the architecture moat degraded over time.

**Mistake 4: Didn't have a client-facing business development leader.**

I was the architect, heads-down on technology. One co-founder led transactional sales (Google Ads, mailing lists). But we never had someone whose job was enterprise relationship building—shaking hands, networking with C-suite, opening doors at Fortune 500 companies.

By Year 4, when I knew enterprise customers were the play, we should have recruited a business development CEO or VP who lived in that world. Someone who could walk into UPS, Sanofi, Deloitte and build real relationships at the executive level.

Instead, our enterprise clients came mostly through inbound and referrals. We left revenue on the table by not having someone whose full-time job was enterprise business development and relationship building.

**Mistake 5: Didn't build strategic partnerships and integrations with platforms our customers used.**

We dealt with employees and HR processes. Our customers were already using Paychex, Intuit, Workday for payroll, accounting, and HR management.

We should have built integrations with those platforms. Make it easy for HR teams to sync employee data, avoid manual entry, embed Censeo into their existing workflow.

Instead, we stayed a standalone tool. Customers had to manually manage data across multiple systems. Smaller HR software companies that integrated with Workday and Paychex became far more valuable and sticky.

By Year 4-5, when we knew enterprise was the play, we should have prioritized ecosystem integrations. That would have accelerated adoption, reduced friction, and made us harder to replace.

**The Meta-Lesson:**

Every founder makes mistakes. The successful ones recognize them, learn, adjust, and don't repeat them. The unsuccessful ones repeat the same mistakes and blame the market.

I made these five mistakes. I learned from them. That learning is why I'm effective in subsequent roles.

For founders: Track your mistakes. Share them with other founders. Don't pretend you're perfect.

---

## Post 6: The CTO Who Built It vs. The CTO Inside the Machine
**Category: Leadership & Organizational Dynamics | Word count: 360**

---

From 2008-2011, I was CTO of Censeo. I owned architecture, product vision, hiring decisions, culture. The classic founder-led tech leader.

After the 2011 acquisition, I became CTO of the Censeo business unit inside Mercer (2011-2014). Same role title, completely different operating environment.

**The difference wasn't being a CTO. It was who I answered to.**

**As CTO of Censeo:**
- Architecture decisions were mine. If I said "we're building for enterprise scale," we built for enterprise scale.
- Revenue model was mine. If profitability meant staying lean, we stayed lean.
- Hiring was mine. If someone didn't fit the culture, they were gone.
- Product vision was mine. If a customer requested something misaligned with our strategy, we said no.

**As CTO of Censeo inside Mercer:**
- Architecture decisions went through layers. Mercer's infrastructure team. Mercer's security. Mercer's platform strategy. My job was making the case, not making the call.
- Revenue model was set by Mercer. We optimized for what Mercer cared about, not what Censeo needed.
- Hiring came from Mercer's talent pool and HR policy. Culture assimilation was mandatory.
- Product vision was negotiated. What customers wanted, Mercer weighed against broader platform strategy.

**The Real Lesson:**

Being a strong CTO inside a company is fundamentally different from being a CTO who built the company. In an enterprise, you influence through credibility, data, and relationships—not authority.

This taught me why founder-led companies and acquired companies operate so differently. And why some CTOs thrive in one environment and struggle in the other.

The best operators understand both: the autonomy and burden of building it yourself, and the constraint and leverage of operating within a larger system. You need both mental models to navigate.

