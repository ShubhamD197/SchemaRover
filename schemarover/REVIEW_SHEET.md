# SchemaRover — Review Sheet (50% milestone)

Everything you need to present today, in plain language.
Read Part 1 and Part 5 out loud twice before you go in.

---

# PART 1 — What to say in the first two minutes

Say this in your own words. Do not rush it.

> "Our project lets someone ask a database a question in plain English and
> get back both the answer and the SQL that produced it.
>
> The hard part is not calling an AI model. The hard part is deciding
> **which tables to show it**. A real company database can have 70 or 200
> tables. If you paste all of them into the prompt, the model gets confused,
> invents columns that do not exist, and the cost goes up with every table.
>
> So before we ask the AI anything, we work out which handful of tables the
> question is actually about, and we show it only those. We use three
> methods together: matching words, matching meaning, and following the
> foreign-key links between tables.
>
> It works on any MySQL, PostgreSQL or SQLite database. Nothing is trained,
> nothing is configured. You paste a connection string and it works."

**The one sentence to repeat if you remember nothing else:**

> **"The retrieval is our contribution. The AI model is just a component."**

---

# PART 2 — How it works (the diagram you explain)

Nine steps. Walk the panel through them in order.

```
1. User pastes a database connection string
2. We read the database structure automatically  (tables, columns, links)
3. Question comes in
                 |
    +------------+------------+
    |                         |
4. WORD match            5. MEANING match
    |                         |
    +------------+------------+
                 |
6. Combine both lists
                 |
7. FOLLOW THE LINKS (foreign keys) to add connecting tables
                 |
8. Build a small prompt with ONLY those tables  ->  send to Gemini
                 |
9. Safety-check the SQL  ->  run it  ->  show the answer AND the SQL
```

**Explain the three stages like this:**

| Stage | What it does | Example | What it cannot do |
|---|---|---|---|
| 1. Word match | Matches words in the question to table and column names | "How many singers" finds the table `singer` | Does not know "movie" means `film` |
| 2. Meaning match | An AI embedding model that understands similar meanings | "movie" finds the table `film` | Fuzzy — needs a cut-off score |
| 3. Follow links | Walks the foreign keys to add connecting tables | "actors and their films" needs `film_actor`, which nobody mentions | Cannot know anything the links do not record |

**Why three and not one:** *"They fail in different ways. Word matching is
exact but literal. Meaning matching handles different words but is fuzzy.
Neither of them can know that joining two tables needs a third linking table
that nobody said out loud — only the foreign keys know that."*

---

# PART 3 — What is finished (this is your 50%)

Tick these off out loud. This is a lot of work; do not undersell it.

**Working software**
- [x] Connect to any MySQL / PostgreSQL / SQLite database at runtime
- [x] Automatic reading of the database structure
- [x] All three retrieval stages built and working
- [x] Prompt builder that sends only the retrieved tables
- [x] Gemini integration, temperature 0 so results repeat exactly
- [x] Safety checker — only read-only SELECT can ever run
- [x] Web dashboard: connection, question box, **live view of which tables
      were retrieved**, generated SQL, results table, history
- [x] Every question logged with timing and table counts

**Measurement (this is what makes it research, not just an app)**
- [x] Evaluation system that scores retrieval automatically
- [x] Tested on **3 databases and 1,134 questions in total**
- [x] Wrote **80 test questions** for a real 68-table business database
- [x] A tool that reads any `.sql` schema file, so we can test big databases
      without installing a database server

**Documentation**
- [x] `DECISIONS.md` — every design choice and *why*, with its cost
- [x] `RESULTS.md` — every number, reproducible with one command
- [x] `PLAN.md` — what is done and what is next

---

# PART 4 — The numbers, explained simply

## First, the two terms you must define before showing any number

Write these on the board if you can.

**"Full recall"** — out of all the questions, how often did we successfully
find **every** table needed to answer it?
*Why it matters:* if even one needed table is missing, the AI cannot possibly
write correct SQL. So this is the **ceiling** on how good the whole system
can ever be.

**"Schema sent"** — what percentage of the database did we have to send to
the AI in order to achieve that?
*Why it matters:* this is our efficiency. Lower is better.

> **Say this clearly:** *"You have to read both numbers together. If you only
> look at full recall, you can always score 100% by sending the whole
> database. That is not retrieval, that is giving up. So we always show both."*

## The headline table

| Database | Size | Questions | Found all tables | Schema we sent |
|---|---|---|---|---|
| Spider (standard benchmark) | 4.5 tables avg | 1034 | 100% | 91.5% |
| Sakila (real DVD-rental DB) | 16 tables | 20 | 85% (17/20) | 70.6% |
| **AdventureWorks (real business DB)** | **68 tables** | **80** | **100% (80/80)** | **48.7%** |

**How to say this:**

> "On the standard benchmark we get 100%. But look at the last column — we had
> to send 91.5% of the database to do it. That is because those databases only
> have four or five tables. There is nothing to filter out.
>
> So we went and got a real business database with 68 tables. There we still
> find every needed table for all 80 questions, but we only send **half** the
> database. The prompt drops from 5,305 tokens to 2,684 — **half the cost**.
>
> And that is the whole point of the project: **the bigger the database, the
> more we save.** On a small database we save nothing, and we are honest
> about that."

## The trend — this is your most important slide

| Database size | Schema we send |
|---|---|
| 4.5 tables | 91.5% |
| 16 tables | 70.6% |
| 68 tables | **48.7%** |

> *"As the database gets bigger, the share we need to send keeps dropping.
> That downward line is our contribution."*

## Proof that each stage is needed (ablation)

On the 68-table database:

| What we switch on | Found all tables |
|---|---|
| Word matching only | 23.8% |
| Word + meaning | 91.2% |
| Word + meaning + follow links | **100%** |

> *"Word matching alone gets less than a quarter. Adding meaning matching
> takes it to 91%. Adding link-following completes it. Each stage earns its
> place — and we prove it with numbers, not opinion."*

On Sakila the proof is even sharper: **word matching alone gets 0 out of 20**,
because the questions say "movie" and the table is called `film`.

---

# PART 5 — Problems we hit and how we solved them

**This is the strongest part of your presentation.** Panels love hearing that
you found your own mistakes. Tell each one as a short story.

### Problem 1: We had no way to know if we were improving
**What happened:** All three stages were built, but we were eyeballing a few
examples. Sometimes it looked right, sometimes wrong. We could not tell
whether a change made things better or worse.

**How we solved it:** We stopped guessing and built an evaluation system. It
runs over a thousand questions automatically and scores us.

**What to say:** *"Our biggest lesson was: build the measuring tool before you
build the thing. Every number I am showing you today comes from that."*

### Problem 2: A one-line bug was costing us 17%
**What happened:** "How many singers do we have?" found nothing — even though
the database had a table literally called `singer`. The code tried to handle
plurals, but it removed the "s" from the **table name** (already singular, so
nothing happened) and never touched the **question**, where the "s" actually
was.

**How we solved it:** Handle plurals on **both** sides.

**Result:** questions that found nothing dropped from 242 to 81. Retrieval
went from 57% to 76%.

**What to say:** *"One line of code was worth 17 percentage points. We would
never have found it without the measurement system."*

### Problem 3: Our benchmark was hiding the truth
**What happened:** We were testing on Spider, the standard benchmark, and
getting 100%. Then we checked how much of the database we were sending: 91.5%.
Those databases only have 4 or 5 tables, so there was nothing to filter. A
system that just sends everything also scores 100%.

**How we solved it:** We downloaded a real business database with 68 tables
and wrote 80 test questions for it ourselves.

**What to say:** *"Our best number turned out to be meaningless, and we found
that out ourselves. That is why we now always report how much of the database
we sent alongside it."*

### Problem 4: Link-following exploded on the real database
**What happened:** On the small benchmark, following the links added about 1
extra table. On the 68-table database it added **15**. Real databases have
"hub" tables — in AdventureWorks, 16 different tables point at `product`. The
moment `product` matched, all 16 came along.

**How we solved it:** We stop expanding outward from a hub. If a table has
more than 8 connections we keep the table itself, but do not drag in its whole
neighbourhood.

**Result:** same 100% retrieval, schema sent dropped from 57.8% to 48.7%, and
the prompt got 15% cheaper. **No downside on any of the three databases.**

**What to say:** *"Interestingly, we had tested a similar idea earlier on the
small benchmark and rejected it, because there it made things worse. It only
becomes the right answer on a big database. The size of your test data changes
your conclusions."*

### Problem 5: The AI could have been tricked into deleting data
**What happened:** Our safety checker removed SQL comments before looking for
dangerous words. So `SELECT * FROM t -- ; DELETE FROM x` looked clean after the
comment was stripped — but the text we would actually send still contained
`DELETE`.

**How we solved it:** Check **both** the cleaned text and the original text,
and refuse any generated SQL containing comment characters at all.

**Be honest:** *"This is a second layer of defence, not a proof. The real
protection is connecting with a database user that only has read permission.
We say that before anyone asks."*

### Problem 6 (found this morning): The AI model had been retired
**What happened:** While testing today, every query failed. The model version
we were using had been switched off by Google. We also found that long queries
were being cut off halfway, because newer models spend part of their output
budget on internal reasoning.

**How we solved it:** Updated the model version and increased the output
budget. Both fixed and re-tested end to end.

**What to say:** *"We test the whole path regularly, which is how we caught
this before the presentation rather than during it."*

---

# PART 6 — What is honestly NOT done yet

Say these before the panel finds them. It builds trust.

1. **We have not measured final answer accuracy yet.** Everything today
   measures whether we found the right *tables*. We have not measured how often
   the final SQL returns the right *answer*. That is the next milestone.
   **Never call our numbers "accuracy" — say "retrieval accuracy".**

2. **Sakila still fails 3 questions out of 20.** We know exactly why. Two need
   the `payment` table for the word "revenue", and the embedding model does not
   connect "revenue" to a column called `amount`. The third asks about "Canada",
   which is a piece of *data*, not a table name — no schema method can find it.
   That is a separate known research problem called value linking.

3. **We only filter tables, not columns.** We send whole tables. One
   AdventureWorks table has 26 columns. Cutting unused columns is the next big
   saving.

4. **48.7% is still too much.** Sending half of a 68-table database is an
   improvement, not yet a triumph.

5. **We wrote the AdventureWorks questions ourselves.** They average 2.3 tables
   per answer while Sakila's average 4.5, so ours may be slightly easier. We
   plan to add harder multi-step questions.

---

# PART 7 — Live demo runsheet

Keep it to about 4 minutes. Practise it once beforehand.

1. **Show the empty dashboard.** *"It knows nothing about any database yet."*
2. **Paste the connection string.** Point at the table count.
   *"Zero configuration — it read the structure by itself."*
3. **Ask a simple question:** *"How many films are there?"*
   - Point at the retrieval panel and the highlighted tables.
   - Point at the generated SQL. *"The user always sees exactly what ran."*
4. **Ask a join question:** *"List film titles and their categories"*
   - Point at the **amber** chips. *"Nobody said 'film_category'. The
     foreign-key graph found it."*
5. **Scroll to the Evaluation section** — the measured results on all three
   databases.
6. **Show the history panel.**

**Connection string for the demo (no MySQL setup needed):**

```
sqlite:///D:/Shubham Dhumal/SchemaRover/spider_data/database/sakila_1/sakila_1.sqlite
```

**To start it:**

```
cd "D:\Shubham Dhumal\SchemaRover\CodeBase\schemarover\backend"
python -m uvicorn main:app --port 8000
```

Then open http://localhost:8000

**If the internet or the API key fails:** go straight to the Evaluation
section and present the measurement story. Say: *"The retrieval works with no
AI model involved at all — these numbers were measured without it."* That is
arguably the stronger demo anyway, because it is evidence rather than a happy
path.

**Expect this and pre-empt it:** on the 16-table demo database we light up
about 10 of the 16 tables. If someone points at that, say:
*"Exactly — on a small database there is little to filter, which is precisely
what we discovered, and why we moved to a 68-table database where we send under
half."*

---

# PART 8 — Questions they will ask, and your answers

**"Isn't this just calling ChatGPT?"**
> "Calling the model is one step out of nine. The contribution is what happens
> before the call — choosing which of 68 tables to show it. We can demonstrate
> the retrieval working with no AI model involved at all."

**"What is your accuracy?"**
> "100% retrieval accuracy on the 68-table database — we find every needed
> table for all 80 questions. That is the ceiling on final accuracy, not final
> accuracy itself. We have not measured end-to-end yet."
>
> **Do not say "100% accuracy" on its own. A knowledgeable panel member will
> catch it and you will lose credibility.**

**"Why not just send the whole schema?"**
> "That works on small databases and breaks on real ones. Cost grows with every
> table, and the model invents joins between unrelated tables. That is exactly
> the comparison we are running as our baseline."

**"How does this compare to the best systems out there?"**
> "Fine-tuned models like RESDSQL score higher on the benchmark. We are not
> competing on raw accuracy — they need training data and GPU time for each
> database. Ours is training-free and zero-config: point it at any database and
> it works immediately. That is a different axis, and it is the one that
> matters for actually deploying this."

**"What if the AI writes something destructive?"**
> "Two layers. The checker only allows a single plain SELECT — we test it
> against stacked statements, table drops and file access. The stronger
> protection is connecting with a read-only database user."

**"Is it reliable and repeatable?"**
> "Temperature zero. Same question, same database, same SQL every time. That is
> required for our results to be reproducible."

**"What is left to do?"**
> "Measure end-to-end answer accuracy, compare against sending the full schema,
> filter columns as well as tables, and produce the scaling graph — accuracy and
> prompt cost versus number of tables. That graph is the centre of our paper."

**"How do we know your test questions are fair?"**
> "We wrote them from the database structure *before* running our system on
> them, and then froze them. The expected tables follow the database's declared
> foreign-key paths. We also state openly that our questions average 2.3 tables
> while the Sakila set averages 4.5, so ours may be slightly easier."

**"Why did you use three methods instead of one?"**
> "Because we measured what each one contributes. Word matching alone gets
> 23.8% on the big database and 0% on Sakila. Adding meaning matching takes it
> to 91%. Adding link-following completes it. We can show the table."

---

# PART 9 — Do not say these

| Do not say | Say instead |
|---|---|
| "We have 100% accuracy" | "100% **retrieval** accuracy on AdventureWorks" |
| "It beats state of the art" | "We compete on being training-free, not on raw score" |
| "It's finished" | "The retrieval half is complete and measured; end-to-end evaluation is next" |
| Quoting Spider's 100% on its own | Always pair it with "but we sent 91.5% of the schema, which is why that number is not the interesting one" |

---

# PART 10 — 60-second cheat card

Numbers to have on the tip of your tongue:

- **3** databases tested, **1,134** questions
- **68** tables in AdventureWorks, **80** questions we wrote for it
- **100%** retrieval on AdventureWorks, sending **48.7%** of the schema
- **2,684 tokens instead of 5,305** — half the prompt cost
- **91.5% → 70.6% → 48.7%** — schema sent, as databases grow 4.5 → 16 → 68 tables
- **23.8% → 91.2% → 100%** — word only, + meaning, + links
- **57% → 76%** — the one-line plural bug we found and fixed
- **+1.3 vs +15.3** — tables added by link-following, small vs large database
