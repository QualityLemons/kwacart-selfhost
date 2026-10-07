"""Form classes for all tool implementations.

Each class in this module maps 1-to-1 to a tool implementation class in
``tools/implementations.py`` and to an entry in ``tools/registry.py``.

Responsibility split
--------------------
* Form-level validation (handled here): confirms that required fields are
  present and non-empty so Django can surface field errors before the tool
  runs.
* Content validation (handled by ``BaseTool.validate``): applies tool-specific
  rules (e.g. minimum length) after the form has passed its own checks.
"""

from django import forms

from .utils import validate_canvas_data


class IdeaGenerationForm(forms.Form):
    initial_thought = forms.CharField(
        widget=forms.Textarea(attrs={'placeholder': 'Your individual reflection (1 min)...'}),
        label="Phase 1: Self-Reflection"
    )


class IAmAndILikeForm(forms.Form):
    # Both fields are optional at the field level because validation requires
    # at least one field to be filled — a constraint that spans fields and
    # is enforced by the clean() method below as well as by
    # IAmAndILikeTool.validate for the range-check (min length).
    i_like = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'I like…',
            'rows': 2,
        }),
        label="I like…",
        required=False,
        max_length=5000,
    )
    i_do_not_like = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'I do not like…',
            'rows': 2,
        }),
        label="I do not like…",
        required=False,
        max_length=5000,
    )

    def clean(self):
        cleaned_data = super().clean()
        likes = (cleaned_data.get('i_like') or '').strip()
        dislikes = (cleaned_data.get('i_do_not_like') or '').strip()
        if not likes and not dislikes:
            raise forms.ValidationError(
                'Please fill in at least one field before saving.'
            )
        return cleaned_data


class UserExperienceFishbowlForm(forms.Form):
    fishbowl_experience = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Inner circle: share the good, the bad, and the ugly — '
                'informally and concretely, as if talking among yourselves. '
                'Avoid presenting to the audience.'
            ),
            'rows': 5,
        }),
        label='Inner circle conversation — what was shared (10–25 min)',
    )
    observations_questions = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Outer circle: what did you observe — including nonverbal exchanges? '
                'What questions emerged in your satellite group?'
            ),
            'rows': 4,
        }),
        label='Outer circle observations and questions (satellite groups, 4 min)',
    )
    qa_exchange = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What questions were put to the inner circle? '
                'What answers or exchanges stood out? '
                'What shifted in the room?'
            ),
            'rows': 4,
        }),
        label='Q&A exchange between inner and outer circles (10–25 min)',
    )
    debrief = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'W³ debrief — What happened? So what does it mean? Now what will you do? '
                'And: what seems possible now that did not before?'
            ),
            'rows': 4,
        }),
        label='W³ debrief — What, So What, Now What, and what seems possible now (10–15 min)',
    )


class ConversationCafeForm(forms.Form):
    theme = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What is the theme or question your group will explore? '
                'Frame it as an open question that invites reflection rather than debate.'
            ),
            'rows': 2,
        }),
        label='Theme or question for the conversation',
    )
    round_one = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Round 1 — talking object: '
                'What are you thinking, feeling, or doing about the theme right now? '
                '(1 min per person, no interrupting)'
            ),
            'rows': 3,
        }),
        label='Round 1 — your initial thoughts, feelings, or actions on the theme (1 min per person)',
    )
    round_two = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Round 2 — talking object: '
                'After listening to everyone, what shifted or deepened for you? '
                '(1 min per person)'
            ),
            'rows': 3,
        }),
        label='Round 2 — what shifted after listening to everyone (1 min per person)',
    )
    open_conversation = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Round 3 — open conversation: '
                'What threads or insights emerged? '
                'What surprised you? What felt most alive in the room?'
            ),
            'rows': 5,
        }),
        label='Round 3 — key threads and insights from the open conversation (20–40 min)',
    )
    takeaway = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Round 4 — talking object: '
                'What do you take away from this conversation? '
                'What will you carry forward?'
            ),
            'rows': 3,
        }),
        label='Round 4 — your takeaway (5–10 min)',
    )


class HelpingHeuristicsForm(forms.Form):
    challenge = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What challenge are you passionate about working on? '
                'Share something real and specific — the more genuine, '
                'the richer the coaching interactions will be.'
            ),
            'rows': 3,
        }),
        label='Your challenge as client',
    )
    quiet_presence = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Round 1 — Quiet Presence: '
                'What did it feel like to be heard with compassionate listening and no advice? '
                'What did you notice as coach or observer?'
            ),
            'rows': 3,
        }),
        label='Round 1 — Quiet Presence (compassionate listening, 2 min)',
    )
    guided_discovery = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Round 2 — Guided Discovery: '
                'What happened when the coach guided inquiry rather than offering solutions? '
                'What was discovered?'
            ),
            'rows': 3,
        }),
        label='Round 2 — Guided Discovery (inquiry for mutual discovery, 2 min)',
    )
    loving_provocation = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Round 3 — Loving Provocation: '
                'What happened when the coach interjected advice and gently challenged? '
                'What did the coach see that the client did not?'
            ),
            'rows': 3,
        }),
        label='Round 3 — Loving Provocation (advice, accepting and blocking, 2 min)',
    )
    process_mindfulness = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Round 4 — Process Mindfulness: '
                'What novel possibilities emerged when both coach and client accepted all offers? '
                'What felt different about this round?'
            ),
            'rows': 3,
        }),
        label='Round 4 — Process Mindfulness (accepting all offers, noticing possibilities, 2 min)',
    )
    debrief = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Which pattern had the most impact? '
                'What did you notice about your own habits of helping, asking, and receiving? '
                'What shift will you make?'
            ),
            'rows': 4,
        }),
        label='Debrief — impact of all four patterns as client, coach, and observer (5 min)',
    )


class ImprovPrototypingForm(forms.Form):
    scenario = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What is the chronic challenge being explored? '
                'Describe the scene, the roles, and the situation to be acted out. '
                'What frustrating pattern are the players depicting?'
            ),
            'rows': 4,
        }),
        label='The challenge and scene — set the stage (3 min)',
    )
    scene_observations = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What worked in the scene? What did not? '
                'List the successful chunks worth keeping and the unsuccessful ones '
                'worth discarding. (Debrief in 1-2-4-All, 5 min.)'
            ),
            'rows': 4,
        }),
        label='Successful and unsuccessful chunks observed in the scene (1-2-4-All, 5 min)',
    )
    prototype = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'How did your group piece the successful chunks together into a new prototype? '
                'Describe what was acted out and what made it better than the original.'
            ),
            'rows': 4,
        }),
        label='Your improved prototype — assembled from the successful chunks (5 min)',
    )
    reflection = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'After all rounds, what prototype or behaviour is good enough to put into practice? '
                'What new insight emerged that you did not have before you started?'
            ),
            'rows': 3,
        }),
        label='What is good enough to put into practice',
    )


class MinSpecsForm(forms.Form):
    max_specs = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'List every must-do and must-not-do you can think of. '
                'Make the list as complete as possible — include everything, '
                'even rules that may turn out to be nonessential.'
            ),
            'rows': 6,
        }),
        label='Max Specs — full list of all must-dos and must-not-dos (1 min alone, 5 min small group)',
    )
    sifting_result = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'For each rule on your Max Spec list, ask: '
                '"If we broke or ignored this rule, could we still achieve our purpose?" '
                'List what was dropped and briefly why. Note what survived the test.'
            ),
            'rows': 5,
        }),
        label='Sifting — what was dropped after testing against the purpose, and what survived',
    )
    min_specs = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Your final, shortest possible list. '
                'Only the rules that are truly essential — '
                'nothing more that can be taken away.'
            ),
            'rows': 4,
        }),
        label='Min Specs — the absolute essentials only',
    )


class WiseCrowdsLargeGroupForm(forms.Form):
    challenge = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Describe your challenge, the status of any work in progress, '
                'and the specific advice or help you are looking for.'
            ),
            'rows': 5,
        }),
        label='Client challenge and request for help (10 min presentation)',
    )
    clarifying_questions = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What clarifying questions did the primary consulting team ask?',
            'rows': 3,
        }),
        label='Clarifying questions from the primary consulting team (10 min)',
    )
    primary_advice = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What joint advice and recommendations did the primary consulting team '
                'develop while the client had their back turned?'
            ),
            'rows': 4,
        }),
        label='Primary consulting team\'s joint advice — client back turned (7 min)',
    )
    satellite_feedback = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What critiques of the primary team\'s advice emerged from satellite teams? '
                'What additional recommendations did they contribute? '
                '(One comment and one recommendation per team, no repeats.)'
            ),
            'rows': 4,
        }),
        label='Critiques and recommendations from satellite teams (10 min)',
    )
    takeaway = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What was most useful? What do you take away from this consultation?',
            'rows': 3,
        }),
        label='Client feedback — what was useful and what you take away (2 min)',
    )
    group_reflection = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What did the full group notice about this process? '
                'So what — why does it matter? '
                'Now what — what actions follow?'
            ),
            'rows': 3,
        }),
        label='Full-group reflection — So What and Now What (5 min)',
    )


class WiseCrowdsForm(forms.Form):
    challenge = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Briefly describe your challenge and what kind of help you are asking for. '
                'Be specific enough that your consultants can give useful advice.'
            ),
            'rows': 4,
        }),
        label='Your challenge and request for help (client presents, 2 min)',
    )
    clarifying_questions = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What questions did your consultants ask to clarify the challenge?',
            'rows': 3,
        }),
        label='Clarifying questions the consultants asked (3 min)',
    )
    consultant_advice = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What advice, recommendations, or ideas did the consultants offer '
                'while you had your back turned? Capture what you heard.'
            ),
            'rows': 5,
        }),
        label='Advice and recommendations from consultants — back turned (8 min)',
    )
    takeaway = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What was most useful? '
                'What will you take away from this consultation?'
            ),
            'rows': 3,
        }),
        label='Your feedback to the consultants — what was useful and what you take away (2 min)',
    )


class TwentyFiveTenCrowdSourcingForm(forms.Form):
    bold_idea = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'If you were ten times bolder, what big idea would you recommend? '
                'What first step would you take to get started?'
            ),
            'rows': 4,
        }),
        label='Your bold idea and first step (write on your index card, 5 min)',
    )
    scores_received = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What five scores (each 1–5) did your card receive across the rounds? '
                'What was the total out of 25?'
            ),
            'rows': 2,
        }),
        label='Scores your card received across the five rounds (total out of 25)',
    )
    top_ideas = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Which ideas scored highest in the countdown from 25? '
                'What surprised you? What caught your attention?'
            ),
            'rows': 4,
        }),
        label='Top ideas that emerged — and what caught your attention (2 min debrief)',
    )


class ShiftAndShareForm(forms.Form):
    innovation_summary = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What is the innovation or program you are sharing? '
                'Describe the essence in a way that helps others see the value — '
                'include a story, example, or object if possible.'
            ),
            'rows': 5,
        }),
        label='Your innovation — what you shared at your station (10 min presentation)',
    )
    questions_feedback = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What questions did visitors ask? '
                'What feedback or reactions stood out? '
                'If you were a visitor, what did you ask or contribute?'
            ),
            'rows': 4,
        }),
        label='Questions and feedback at your station (2 min per visit)',
    )
    key_takeaways = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What innovations did you see at other stations? '
                'What ideas sparked your thinking? '
                'Any potential collaborations or follow-ups?'
            ),
            'rows': 4,
        }),
        label='What you learned visiting other stations',
    )


class DiscoveryActionDialogueForm(forms.Form):
    problem_presence = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What signals or signs tell you the problem is present?',
            'rows': 3,
        }),
        label='Q1 — How do you know when the problem is present?',
    )
    effective_contributions = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What specific actions or approaches do you take that actually help?',
            'rows': 3,
        }),
        label='Q2 — How do you contribute effectively to solving it?',
    )
    barriers = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What gets in the way of doing those things consistently?',
            'rows': 3,
        }),
        label='Q3 — What prevents you from doing this all the time?',
    )
    positive_deviants = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Who in this group or community manages to solve this more often? '
                'What behaviours or practices make their success possible?'
            ),
            'rows': 3,
        }),
        label='Q4 — Who frequently overcomes these barriers, and how?',
    )
    ideas = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'Any ideas for solving this problem or removing barriers?',
            'rows': 3,
        }),
        label='Q5 — Do you have any ideas?',
    )
    next_steps = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What concrete steps need to happen? Who is willing to take them on?',
            'rows': 3,
        }),
        label='Q6 — What needs to happen? Any volunteers?',
    )
    who_else = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'Who else should be part of this conversation or effort?',
            'rows': 3,
        }),
        label='Q7 — Who else needs to be involved?',
    )


class WhatSoWhatNowWhatForm(forms.Form):
    what = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What happened? What did you notice? '
                'What facts or observations stood out? (Stick to observable facts — save interpretations for So What)'
            ),
            'rows': 4,
        }),
        label='WHAT? — Facts and observations (1 min alone, then small group)',
    )
    so_what = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Why is that important? '
                'What patterns or conclusions are emerging? '
                'What hypotheses can you make?'
            ),
            'rows': 4,
        }),
        label='SO WHAT? — Patterns and conclusions (1 min alone, then small group)',
    )
    now_what = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What actions make sense? What will you do differently?',
            'rows': 4,
        }),
        label='NOW WHAT? — Actions (1 min alone, small group, then whole group)',
    )


class TroikaConsultingForm(forms.Form):
    consulting_question = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What is your challenge? '
                'What kind of help do you need from your consultants?'
            ),
            'rows': 3,
        }),
        label='Your consulting question (reflect alone, 1 min)',
    )
    consultant_advice = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What ideas, suggestions, or coaching advice did you offer '
                'while acting as a consultant for your colleagues?'
            ),
            'rows': 4,
        }),
        label='Advice you gave as a consultant',
    )
    valuable_takeaway = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What was most valuable about what you heard when you were the client? '
                'What will you take away?'
            ),
            'rows': 3,
        }),
        label='Most valuable takeaway from your client turn (1–2 min)',
    )


class FifteenPercentSolutionsForm(forms.Form):
    solutions_list = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What is your 15 percent? Where do you have discretion and freedom to act? '
                'What can you do without more resources or authority?'
            ),
            'rows': 5,
        }),
        label='Your 15% Solutions (individual, 5 min)',
    )
    group_share = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What did you share with your group? What did others share that resonated with you?',
            'rows': 4,
        }),
        label='Small group share (3 min per person)',
    )
    consultation_insights = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What clarifying questions did you receive? What advice was offered or given?',
            'rows': 4,
        }),
        label='Group consultation — questions and advice (5–7 min per person)',
    )


class TrizForm(forms.Form):
    worst_result_list = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'List everything you could do to guarantee the worst result '
                'imaginable for your top strategy or objective…'
            ),
            'rows': 5,
        }),
        label='Step 1 — How to guarantee the worst result (10 min)',
    )
    current_resemblances = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Go through your list above item by item. '
                'Which items are you currently doing — or doing something that resembles them?'
            ),
            'rows': 5,
        }),
        label='Step 2 — What you currently do that resembles the worst-result list (10 min)',
    )
    stop_first_steps = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'For each item from Step 2, what is your first step to stop doing it? '
                'Be concrete and specific.'
            ),
            'rows': 5,
        }),
        label='Step 3 — First steps to stop each counterproductive activity (10 min)',
    )


class AppreciativeInterviewsForm(forms.Form):
    success_story = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Tell a story about a time when your work was at its best. '
                'What happened? What did you do? '
                'What made it exceptional rather than ordinary?'
            ),
            'rows': 5,
        }),
        label='Your success story — a time when your work was at its best (pairs, 15–20 min)',
    )
    success_conditions = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What conditions, assets, or factors made that success possible? '
                'What did you have that you do not always have?'
            ),
            'rows': 4,
        }),
        label='What made that success possible',
    )
    partner_story = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Retell your partner\'s story for a group of four. '
                'What patterns of success did you notice across both stories?'
            ),
            'rows': 4,
        }),
        label='Your partner\'s story retold — and patterns you noticed (groups of 4, 15 min)',
    )
    group_patterns = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What conditions and assets for success did the whole group identify? '
                'What do the stories have in common?'
            ),
            'rows': 4,
        }),
        label='Conditions and assets for success collected by the whole group (10–15 min)',
    )
    opportunities = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'How are we investing in these assets right now? '
                'What opportunities do you see to do more of what works?'
            ),
            'rows': 3,
        }),
        label='How we invest in these assets — and what opportunities exist (10 min)',
    )


class WickedQuestionsForm(forms.Form):
    individual_questions = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Write Wicked Questions in this format: '
                '"How is it that we are [A] AND [opposite of A] at the same time?" '
                'Aim for 2–3 questions (individual, 5 min).'
            ),
            'rows': 5,
        }),
        label='Your Wicked Questions — pairs of opposites (individual, 5 min)',
    )
    group_question = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Which of your small group\'s Wicked Questions felt most impactful '
                'or generated the most energy?'
            ),
            'rows': 3,
        }),
        label='Your small group\'s most impactful Wicked Question (5 min)',
    )
    whole_group_refinement = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What emerged from sharing across all small groups? '
                'What Wicked Questions were refined or combined by the whole group?'
            ),
            'rows': 4,
        }),
        label='Refined Wicked Questions from the whole group (10 min)',
    )


class NineWhysForm(forms.Form):
    activities = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'List the activities you do in your work.',
            'rows': 3,
        }),
        label='Your activities (before interview)',
    )
    why_chain = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Record each answer to "Why is that important to you?" '
                'Aim for at least five iterations before the conversation naturally ends.'
            ),
            'rows': 5,
        }),
        label='Your why-chain — answers to repeated "Why is that important?" (10 min pairs)',
    )
    fundamental_purpose = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What purpose did you arrive at after following the chain? '
                'Express it in one clear sentence.'
            ),
            'rows': 2,
        }),
        label='The fundamental purpose at the end of your why-chain',
    )
    foursome_insights = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What did you notice when you compared your purpose with others\' in your group of four? '
                'What was similar? What surprised you?'
            ),
            'rows': 3,
        }),
        label='Insights and experiences shared in your foursome (5 min)',
    )
    group_reflection = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'How do your individual purposes influence the group\'s next steps? '
                'What connections or tensions emerged in the whole-group reflection?'
            ),
            'rows': 3,
        }),
        label='How your purposes influence next steps — whole-group reflection (5 min)',
    )


class ImpromptNetworkingForm(forms.Form):
    challenge = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What challenge are you working on that you\'d like help with '
                'or to think through with others?'
            ),
            'rows': 3,
        }),
        label='Your challenge (before rounds begin)',
    )
    give_and_get = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What do you hope to get from this group today? '
                'What can you offer others?'
            ),
            'rows': 3,
        }),
        label='What you hope to get from and give the group (before rounds begin)',
    )
    round_one = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What did you hear / share in Round 1? (4–5 min)',
            'rows': 3,
        }),
        label='Notes from Round 1 (4–5 min)',
    )
    round_two = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What did you hear / share in Round 2? (4–5 min)',
            'rows': 3,
        }),
        label='Notes from Round 2 (4–5 min)',
    )
    round_three = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What patterns or insights emerged across all three rounds?',
            'rows': 3,
        }),
        label='Notes from Round 3 (4–5 min)',
    )


class DrawingTogetherForm(forms.Form):
    challenge = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Describe the challenge, question, or situation to be drawn. '
                'Use symbolic or metaphorical imagery — it does not need to be literal.'
            ),
            'rows': 3,
        }),
        label='The challenge or journey',
    )
    canvas_data = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
    )
    interpretation = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What did others see in your drawing? '
                'What symbols or patterns did they interpret — especially things that surprised you?'
            ),
            'rows': 4,
        }),
        label='Interpretation — what others saw',
    )
    insights = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'After sharing drawings with the group — what does the drawing reveal? '
                'What patterns appeared? What became clearer?'
            ),
            'rows': 4,
        }),
        label='Insights — what the drawing reveals',
    )


class ProjectVisionMapForm(forms.Form):
    """A concise, text-first version of Floop Projector's project map."""

    project_goal = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What are you trying to accomplish with this project?',
            'rows': 3,
        }),
        label='Project goal',
    )
    intended_difference = forms.CharField(
        widget=forms.Textarea(attrs={'placeholder': 'What difference will this make?', 'rows': 3}),
        label='Intended difference',
        required=False,
    )
    desired_outcome = forms.CharField(
        widget=forms.Textarea(attrs={'placeholder': 'What will success look like?', 'rows': 3}),
        label='Desired outcome',
        required=False,
    )
    requirements = forms.CharField(
        widget=forms.Textarea(attrs={'placeholder': 'What must be in place?', 'rows': 3}),
        label='Requirements',
        required=False,
    )
    best_case = forms.CharField(
        widget=forms.Textarea(attrs={'placeholder': 'If this goes especially well, what happens?', 'rows': 3}),
        label='Best case',
        required=False,
    )
    worst_case = forms.CharField(
        widget=forms.Textarea(attrs={'placeholder': 'What risks or unwanted outcome should you plan for?', 'rows': 3}),
        label='Worst case',
        required=False,
    )


class VisualReflectionCanvasForm(forms.Form):
    canvas_data = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
        validators=[validate_canvas_data],
    )
    canvas_description = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'Describe your drawing or share your reflection in words.',
            'rows': 4,
        }),
        label='Accessible text alternative or reflection',
        required=False,
    )

    def clean(self):
        cleaned_data = super().clean()
        if not (cleaned_data.get('canvas_data') or '').strip() and not (
            cleaned_data.get('canvas_description') or ''
        ).strip():
            raise forms.ValidationError('Please add a drawing or a text description.')
        return cleaned_data


class MoodSketchCheckInForm(forms.Form):
    MOOD_CHOICES = (
        ('energized', 'Energized'),
        ('hopeful', 'Hopeful'),
        ('calm', 'Calm'),
        ('uncertain', 'Uncertain'),
        ('stretched', 'Stretched'),
        ('concerned', 'Concerned'),
    )

    mood = forms.ChoiceField(
        choices=MOOD_CHOICES,
        label='How are you feeling?',
        widget=forms.RadioSelect,
        required=True,
    )
    reflection = forms.CharField(
        widget=forms.Textarea(attrs={'placeholder': 'Optional short reflection', 'rows': 3}),
        label='Short reflection',
        required=False,
        max_length=1000,
    )
    canvas_data = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
        validators=[validate_canvas_data],
    )


class CelebratingAndMourningForm(forms.Form):
    what_we_celebrate = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What achievements, moments, or contributions from this period '
                'are worth celebrating? Be specific.'
            ),
            'rows': 4,
        }),
        label='What we celebrate',
    )
    what_we_mourn = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What losses, disappointments, or missed opportunities from this period '
                'are worth acknowledging? Be honest.'
            ),
            'rows': 4,
        }),
        label='What we mourn',
    )
    what_we_carry_forward = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What will you carry forward from both the celebrations and the mourning? '
                'What matters enough to hold on to?'
            ),
            'rows': 4,
        }),
        label='What we carry forward',
    )


class OpenSpaceTechnologyForm(forms.Form):
    session_theme = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What topic did you convene or attend? '
                'What question or issue brought people together?'
            ),
            'rows': 3,
        }),
        label='The session theme or question',
    )
    who_joined = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Who showed up? How many people? '
                'What brought them to this particular session?'
            ),
            'rows': 3,
        }),
        label='Who joined and why',
    )
    key_discussion = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What was the substance of the conversation? '
                'What ideas, concerns, or insights emerged?'
            ),
            'rows': 5,
        }),
        label='The key discussion — what emerged',
    )
    outcomes_and_actions = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What outcomes or next steps did the group agree on? '
                'Who is taking what action?'
            ),
            'rows': 4,
        }),
        label='Outcomes and actions from the session',
    )


class GenRelStarForm(forms.Form):
    individual_assessment = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Rate each STAR element:\n'
                'S — How diverse are we? Do we draw out different perspectives?\n'
                'T — How well are we in tune with one another?\n'
                'A — How much do we act together?\n'
                'R — How clear and important is our shared purpose?'
            ),
            'rows': 5,
        }),
        label='Your individual STAR assessment (5 min)',
    )
    small_group_consensus = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'Where did your small group agree? Where did placements differ? '
                'What was the consensus on each STAR element?'
            ),
            'rows': 4,
        }),
        label='Small group consensus and differences (5 min)',
    )
    results_type = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What kind of results does your STAR pattern produce? '
                'E.g. high Tuning + no Action = we get along well but accomplish little.'
            ),
            'rows': 3,
        }),
        label='What type of results does your current STAR pattern generate? (5 min)',
    )
    action_steps = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What actions would boost the elements that need attention? '
                'Generate options before narrowing down.'
            ),
            'rows': 4,
        }),
        label='Action steps to boost the elements needing attention (5 min)',
    )
    first_steps = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': (
                'What first steps can you take right now — today or this week — '
                'to shift your STAR pattern?'
            ),
            'rows': 3,
        }),
        label='First steps you can take right now (whole group, 5 min)',
    )


class InterocepterForm(forms.Form):
    creator_and_date = forms.CharField(
        widget=forms.TextInput(attrs={
            'placeholder': 'e.g. Maria Chen — 14 May 2025',
        }),
        label='Project creator and date',
    )
    project_name = forms.CharField(
        widget=forms.TextInput(attrs={
            'placeholder': 'e.g. Onboarding Overhaul',
        }),
        label='Project name',
    )
    purpose = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What do you want to accomplish? (3 min)',
            'rows': 3,
        }),
        label='Purpose — what you want to accomplish',
    )
    importance = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What\'s the biggest difference this will make? (3 min)',
            'rows': 3,
        }),
        label='Importance — the biggest difference this will make',
    )
    ideal_outcome = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What does the completed project look like? (3 min)',
            'rows': 3,
        }),
        label='Ideal outcome — what the completed project looks like',
    )
    success_criteria = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What has to be true when the project is finished? (10 min)',
            'rows': 5,
        }),
        label='Success criteria — what must be true when finished',
    )
    best_result = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What is the best result if you do take action? (3 min)',
            'rows': 3,
        }),
        label='Best result if you take action',
    )
    worst_result = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What is the worst result if you don\'t take action? (3 min)',
            'rows': 3,
        }),
        label='Worst result if you don\'t take action',
    )


class OneTwoFourAllForm(forms.Form):
    self_reflection = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What is your individual reflection on the question? (1 min)',
            'rows': 3,
        }),
        label='Individual reflection (1 min)',
    )
    pair_ideas = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What ideas or insights emerged from your pair conversation? (2 min)',
            'rows': 3,
        }),
        label='Ideas from your pair (2 min)',
    )
    foursome_ideas = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What ideas or themes emerged from your group of four? (4 min)',
            'rows': 3,
        }),
        label='Ideas from your foursome (4 min)',
    )
    standout_idea = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What is the one idea worth sharing with the full group? (5 min)',
            'rows': 3,
        }),
        label='One standout idea to share with everyone (5 min)',
    )


class FiveStructuralElementsForm(forms.Form):
    pair_one_challenge = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What challenge are you bringing to this first pair conversation?',
            'rows': 3,
        }),
        label='Pair 1 — challenge you bring',
    )
    pair_one_hope = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What do you hope to get from or give to your first partner?',
            'rows': 3,
        }),
        label='Pair 1 — hope to get or give',
    )
    pair_two_challenge = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What challenge are you bringing to this second pair conversation?',
            'rows': 3,
        }),
        label='Pair 2 — challenge you bring',
    )
    pair_two_hope = forms.CharField(
        widget=forms.Textarea(attrs={
            'placeholder': 'What do you hope to get from or give to your second partner?',
            'rows': 3,
        }),
        label='Pair 2 — hope to get or give',
    )
