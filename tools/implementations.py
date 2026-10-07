"""Concrete BaseTool implementations for every tool in the catalog.

Each class inherits from ``BaseTool`` and implements the ``validate`` and
``process`` abstract methods.

PHASES convention
-----------------
Most tools define a ``PHASES`` class attribute — a tuple of
``(field_name, display_label)`` pairs.  The ``field_name`` must match the
corresponding form field name in ``tools/forms.py`` and is used as the key
in both ``payload_input`` and ``payload_output`` on the ``ToolInstance``
model.  The ``display_label`` is shown to the user in the form and in the
archive detail view.

``IdeaGenerationTool`` and ``IAmAndILikeTool`` predate the ``PHASES``
convention and handle their fields manually rather than iterating over a
tuple.
"""

from .interface import BaseTool


class IdeaGenerationTool(BaseTool):
    name = 'Idea Generation'
    description = 'Capture an individual reflection as the start of an idea-generation session.'
    version = '1.0'

    def validate(self):
        text = (self.user_input.get('initial_thought') or '').strip()
        if len(text) < 5:
            self.errors['initial_thought'] = 'Please write a slightly longer reflection.'

    def process(self):
        text = (self.user_input.get('initial_thought') or '').strip()
        return {
            'initial_thought': text,
        }


class IAmAndILikeTool(BaseTool):
    name = 'I am and I like'
    description = 'Each person shares their name with something they like or do not like.'
    version = '1.0'

    def validate(self):
        likes = (self.user_input.get('i_like') or '').strip()
        dislikes = (self.user_input.get('i_do_not_like') or '').strip()
        if not likes and not dislikes:
            self.errors['i_like'] = 'Please fill in at least one field.'

    def process(self):
        likes = (self.user_input.get('i_like') or '').strip()
        dislikes = (self.user_input.get('i_do_not_like') or '').strip()
        parts = []
        if likes:
            parts.append(f'I like {likes}')
        if dislikes:
            parts.append(f'I do not like {dislikes}')
        # Three possible output cases:
        #   both filled  → "I like X and I do not like Y"
        #   likes only   → "I like X"
        #   dislikes only→ "I do not like Y"
        return {
            'statement': ' and '.join(parts) if parts else '',
            'i_like': likes,
            'i_do_not_like': dislikes,
        }


class UserExperienceFishbowlTool(BaseTool):
    name = 'User Experience Fishbowl'
    description = (
        'Share know-how gained from experience with a larger community. '
        'A small inner circle talks openly about the good, the bad, and the ugly; '
        'the outer circle listens, then asks questions in a structured exchange.'
    )
    version = '1.0'

    PHASES = (
        ('fishbowl_experience', 'Inner circle conversation — the good, the bad, and the ugly (10–25 min)'),
        ('observations_questions', 'Outer circle observations and questions formulated in satellite groups (4 min)'),
        ('qa_exchange',          'Q&A exchange between inner and outer circles (10–25 min)'),
        ('debrief',              'W³ debrief — What? So What? Now What? And: what seems possible now? (10–15 min)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            # 3-character minimum intentionally keeps the barrier low while
            # rejecting completely empty or trivially short (e.g. "ok") answers.
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            # Returned dict keys match PHASES field names and are stored
            # verbatim as payload_output on the ToolInstance.
            result[field] = value
        return result


class ConversationCafeTool(BaseTool):
    name = 'Conversation Café'
    description = (
        'Engage everyone in making sense of profound challenges. '
        'Four rounds of structured dialogue — using a talking object — '
        'create calm, deep conversation with less debate and more listening.'
    )
    version = '1.0'

    PHASES = (
        ('theme',             'The theme or question for the conversation'),
        ('round_one',         'Round 1 (talking object): what you are thinking, feeling, '
                              'or doing about the theme (1 min per person)'),
        ('round_two',         'Round 2 (talking object): what shifted after listening to everyone (1 min per person)'),
        ('open_conversation', 'Round 3: key threads and insights from the open conversation (20–40 min)'),
        ('takeaway',          'Round 4 (talking object): your takeaway from the whole conversation (5–10 min)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class HelpingHeuristicsTool(BaseTool):
    name = 'Helping Heuristics'
    description = (
        'Practice progressive methods for helping others, receiving help, '
        'and asking for help. Four rounds — Quiet Presence, Guided Discovery, '
        'Loving Provocation, and Process Mindfulness — reveal your interaction patterns.'
    )
    version = '1.0'

    PHASES = (
        ('challenge',           'The challenge shared as client (passionate, specific)'),
        ('quiet_presence',      'Round 1 — Quiet Presence: coach accepts all offers with '
                                'compassionate listening (2 min)'),
        ('guided_discovery',    'Round 2 — Guided Discovery: coach guides inquiry for mutual discoveries (2 min)'),
        ('loving_provocation',  'Round 3 — Loving Provocation: coach interjects advice, '
                                'accepting and blocking as needed (2 min)'),
        ('process_mindfulness', 'Round 4 — Process Mindfulness: coach and client accept all '
                                'offers, noticing novel possibilities (2 min)'),
        ('debrief',             'Debrief — impact of all four patterns as client, coach, and observer (5 min)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class ImprovPrototypingTool(BaseTool):
    name = 'Improv Prototyping'
    description = (
        'Develop effective solutions to chronic challenges through acting, '
        'observation, and rapid prototyping. Tap explicit, tacit, and latent '
        'knowledge simultaneously — seriously fun and seriously useful.'
    )
    version = '1.0'

    PHASES = (
        ('scenario',          'The chronic challenge and scene to be acted out (set the stage, 3 min)'),
        ('scene_observations', 'Successful and unsuccessful chunks identified from '
                               'the scene (1-2-4-All debrief, 5 min)'),
        ('prototype',         'Your improved prototype built from the successful chunks (small-group act-out, 5 min)'),
        ('reflection',        'What emerged as good enough to put into practice'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class MinSpecsTool(BaseTool):
    name = 'Min Specs'
    description = (
        'Specify only the absolute must-dos and must-not-dos for achieving a purpose. '
        'Generate a full list of rules, sift ruthlessly by testing each against the '
        'purpose, and consolidate to the shortest possible enabling list.'
    )
    version = '1.0'

    PHASES = (
        ('max_specs',      'All must-dos and must-not-dos — generate as complete a list '
                           'as possible (1 min alone, 5 min small group)'),
        ('sifting_result', 'Which rules were dropped after testing against the purpose? Which survived the cut?'),
        ('min_specs',      'Your final minimum list — only the absolute essentials'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class WiseCrowdsLargeGroupTool(BaseTool):
    name = 'Wise Crowds (Large Group)'
    description = (
        'Tap the wisdom of a large group in a structured 1-hour consultation. '
        'One client, a primary consulting team at the front, and multiple satellite '
        'teams — all contributing advice in timed rounds.'
    )
    version = '1.0'

    PHASES = (
        ('challenge',          'Client presents the challenge and request for help (10 min)'),
        ('clarifying_questions', 'Clarifying questions from the primary consulting team (10 min)'),
        ('primary_advice',     'Primary consulting team\'s joint advice — client back turned (7 min)'),
        ('satellite_feedback', 'Critiques and recommendations from satellite teams (10 min)'),
        ('takeaway',           'Client feedback: what was useful and what they take away (2 min)'),
        ('group_reflection',   'Full-group reflection: So What and Now What (5 min)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class WiseCrowdsTool(BaseTool):
    name = 'Wise Crowds'
    description = (
        'Tap the wisdom of the whole group in rapid cycles. '
        'Each person takes a turn as client — presenting a challenge, '
        'receiving clarifying questions, then listening with their back turned '
        'while consultants advise freely.'
    )
    version = '1.0'

    PHASES = (
        ('challenge',            'Your challenge and request for help (client presents, 2 min)'),
        ('clarifying_questions', 'Clarifying questions consultants asked you (3 min)'),
        ('consultant_advice',    'Advice and recommendations from consultants while your back was turned (8 min)'),
        ('takeaway',             'What was useful and what you take away (client feedback, 2 min)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class TwentyFiveTenCrowdSourcingTool(BaseTool):
    name = '25/10 Crowd Sourcing'
    description = (
        'Rapidly generate and sift a group\'s most powerful actionable ideas. '
        'Everyone writes a bold idea and first step, passes cards through five '
        'scoring rounds, and the top ten rise to the surface.'
    )
    version = '1.0'

    PHASES = (
        ('bold_idea',    'Your bold idea and first step (write on your index card, 5 min)'),
        ('scores_received', 'The five scores your card received across the rounds (total out of 25)'),
        ('top_ideas',    'Ideas that rose to the top — what caught your attention? (2 min debrief)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class ShiftAndShareTool(BaseTool):
    name = 'Shift & Share'
    description = (
        'Spread good ideas and make informal connections with innovators. '
        'A few presenters set up stations; small groups rotate through each '
        'one for a 10-minute presentation and feedback round.'
    )
    version = '1.0'

    PHASES = (
        ('innovation_summary', 'Your innovation — what you shared or are sharing at your station (10 min each)'),
        ('questions_feedback',  'Questions and feedback received (or given) at your station (2 min each)'),
        ('key_takeaways',       'What you learned from visiting other stations'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class DiscoveryActionDialogueTool(BaseTool):
    name = 'Discovery & Action Dialogue'
    description = (
        'Discover, invent, and unleash local solutions to chronic problems. '
        'Seven progressive questions surface positive-deviant practices hidden '
        'within the group itself.'
    )
    version = '1.0'

    PHASES = (
        ('problem_presence',       'Q1 — How do you know when the problem is present?'),
        ('effective_contributions', 'Q2 — How do you contribute effectively to solving it?'),
        ('barriers',               'Q3 — What prevents you from doing this all the time?'),
        ('positive_deviants',      'Q4 — Who frequently overcomes these barriers, '
                                   'and what makes their success possible?'),
        ('ideas',                  'Q5 — Do you have any ideas?'),
        ('next_steps',             'Q6 — What needs to happen? Any volunteers?'),
        ('who_else',               'Q7 — Who else needs to be involved?'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class WhatSoWhatNowWhatTool(BaseTool):
    name = 'What, So What, Now What?'
    description = (
        'Together, look back on progress to date and decide what adjustments '
        'are needed. Three stages — facts, sense-making, and action — build '
        'shared understanding and spur coordinated action.'
    )
    version = '1.0'

    PHASES = (
        ('what',      'WHAT? Facts and observations you noticed (1 min alone, then small group)'),
        ('so_what',   'SO WHAT? Patterns, conclusions, and hypotheses emerging (1 min alone, then small group)'),
        ('now_what',  'NOW WHAT? Actions that make sense (1 min alone, small group, then whole group)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class TroikaConsultingTool(BaseTool):
    name = 'Troika Consulting'
    description = (
        'Get practical and imaginative help from colleagues immediately. '
        'Round-robin peer consultations in trios — each person takes a turn '
        'as client while the other two act as consultants.'
    )
    version = '1.0'

    PHASES = (
        ('consulting_question', 'Your challenge and the help you need (client reflection, 1 min)'),
        ('consultant_advice',   'Ideas, suggestions, and coaching advice you gave as a consultant'),
        ('valuable_takeaway',   'What was most valuable from your time as client (1–2 min)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class FifteenPercentSolutionsTool(BaseTool):
    name = '15% Solutions'
    description = (
        'Discover and focus on what each person has the freedom and resources '
        'to do right now. Reveal actions, however small, that create momentum.'
    )
    version = '1.0'

    PHASES = (
        ('solutions_list',       'Your 15% Solutions — what you can do without more '
                                 'resources or authority (individual, 5 min)'),
        ('group_share',          'What you shared with your small group and what you '
                                 'heard from others (3 min per person)'),
        ('consultation_insights', 'Clarifying questions and advice from the group consultation (5–7 min per person)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class TrizTool(BaseTool):
    name = 'TRIZ'
    description = (
        'Stop counterproductive activities and behaviours to make space for '
        'innovation. Three rounds of creative destruction using inversion.'
    )
    version = '1.0'

    PHASES = (
        ('worst_result_list',    'Everything you could do to guarantee the worst result (10 min)'),
        ('current_resemblances', 'What you are currently doing that resembles items on that list (10 min)'),
        ('stop_first_steps',     'First steps to stop each counterproductive activity (10 min)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class AppreciativeInterviewsTool(BaseTool):
    name = 'Appreciative Interviews'
    description = (
        'Discover and build on the root causes of success. '
        'In under an hour, a group of any size generates the conditions '
        'essential for its success by uncovering hidden success stories.'
    )
    version = '1.0'

    PHASES = (
        ('success_story',      'Your success story (pairs, 15–20 min)'),
        ('success_conditions', 'What made the success possible?'),
        ('partner_story',      'Your partner\'s story retold — and patterns you noticed (groups of 4, 15 min)'),
        ('group_patterns',     'Conditions and assets for success collected by the whole group (10–15 min)'),
        ('opportunities',      'How are we investing in these assets? What opportunities do you see? (10 min)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class WickedQuestionsTool(BaseTool):
    name = 'Wicked Questions'
    description = (
        'Articulate the paradoxical challenges a group must confront to succeed. '
        'Surface opposing-yet-complementary strategies that must be pursued simultaneously.'
    )
    version = '1.0'

    PHASES = (
        ('individual_questions',  'Your Wicked Questions — pairs of opposites (individual, 5 min)'),
        ('group_question',        'Your small group\'s most impactful Wicked Question (5 min)'),
        ('whole_group_refinement', 'Refined Wicked Questions from the whole group (10 min)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class NineWhysTool(BaseTool):
    name = 'Nine Whys'
    description = (
        'Make the purpose of your work together clear. '
        'Through repeated "Why?" questions, individuals and groups '
        'surface the fundamental purpose behind their work.'
    )
    version = '1.0'

    PHASES = (
        ('activities',           'Your activities (before interview)'),
        ('why_chain',            'Your why-chain — answers to repeated "Why is that important?" (10 min pairs)'),
        ('fundamental_purpose',  'The fundamental purpose you reached at the end of your why-chain'),
        ('foursome_insights',    'Insights and experiences shared in your foursome (5 min)'),
        ('group_reflection',     'How your purposes influence next steps — whole-group reflection (5 min)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class ImpromptNetworkingTool(BaseTool):
    name = 'Impromptu Networking'
    description = (
        'Rapidly share challenges and expectations, build new connections. '
        'Three rounds of pair conversations in 20 minutes.'
    )
    version = '1.0'

    PHASES = (
        ('challenge',   'Your challenge (before rounds begin)'),
        ('give_and_get', 'What you hope to get from and give the group (before rounds begin)'),
        ('round_one',   'Notes from Round 1 (4–5 min)'),
        ('round_two',   'Notes from Round 2 (4–5 min)'),
        ('round_three', 'Notes from Round 3 (4–5 min)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class OneTwoFourAllTool(BaseTool):
    name = '1-2-4-All'
    description = (
        'Engage everyone simultaneously in generating questions, ideas, and '
        'suggestions. Moves from individual reflection through pairs and '
        'foursomes to a whole-group share-out.'
    )
    version = '1.0'

    PHASES = (
        ('self_reflection',  'Individual reflection (1 min)'),
        ('pair_ideas',       'Ideas from your pair (2 min)'),
        ('foursome_ideas',   'Ideas from your foursome (4 min)'),
        ('standout_idea',    'One standout idea to share with everyone (5 min)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class DrawingTogetherTool(BaseTool):
    name = 'Drawing Together'
    description = (
        'Reveal insights and paths forward through nonverbal expression. '
        'Participants draw a story about a challenge using five universal symbols, '
        'then invite others to interpret their drawings.'
    )
    version = '1.0'

    TEXT_FIELDS = (
        ('challenge',      'The challenge or journey'),
        ('interpretation', 'Interpretation — what others saw'),
        ('insights',       'Insights — what the drawing reveals'),
    )

    def validate(self):
        for field, label in self.TEXT_FIELDS:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.TEXT_FIELDS:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        canvas_data = (self.user_input.get('canvas_data') or '').strip()
        result['canvas_data'] = canvas_data
        result['has_drawing'] = canvas_data.startswith('data:image/')
        return result


class ProjectVisionMapTool(BaseTool):
    name = 'Project Vision Map'
    description = 'Map a project goal, its intended difference, outcomes, requirements, and stakes.'
    version = '1.0'

    FIELDS = (
        ('project_goal', 'Project goal'),
        ('intended_difference', 'Intended difference'),
        ('desired_outcome', 'Desired outcome'),
        ('requirements', 'Requirements'),
        ('best_case', 'Best case'),
        ('worst_case', 'Worst case'),
    )

    def validate(self):
        if len((self.user_input.get('project_goal') or '').strip()) < 10:
            self.errors['project_goal'] = 'Please describe the project goal in a little more detail.'

    def process(self):
        return {
            field: (self.user_input.get(field) or '').strip()
            for field, _ in self.FIELDS
        }


class VisualReflectionCanvasTool(BaseTool):
    name = 'Visual Reflection Canvas'
    description = 'Reflect through drawing, with an accessible text alternative alongside it.'
    version = '1.0'

    def validate(self):
        if not any((self.user_input.get(field) or '').strip() for field in (
            'canvas_data', 'canvas_description',
        )):
            self.errors['canvas_description'] = 'Please add a drawing or a text description.'

    def process(self):
        canvas_data = (self.user_input.get('canvas_data') or '').strip()
        description = (self.user_input.get('canvas_description') or '').strip()
        return {
            'canvas_description': description,
            'canvas_data': canvas_data,
            'has_drawing': bool(canvas_data),
        }


class MoodSketchCheckInTool(BaseTool):
    name = 'Mood & Sketch Check-In'
    description = 'Share a mood, a short reflection, or a sketch to check in with the group.'
    version = '1.0'

    def validate(self):
        if not (self.user_input.get('mood') or '').strip():
            self.errors['mood'] = 'Please choose the mood that fits best.'

    def process(self):
        canvas_data = (self.user_input.get('canvas_data') or '').strip()
        return {
            'mood': (self.user_input.get('mood') or '').strip(),
            'reflection': (self.user_input.get('reflection') or '').strip(),
            'canvas_data': canvas_data,
            'has_drawing': bool(canvas_data),
        }


class FiveStructuralElementsTool(BaseTool):
    name = 'Five Structural Elements'
    description = 'Pairs share challenges and hopes to build new connections.'
    version = '1.0'

    FIELDS = (
        'pair_one_challenge',
        'pair_one_hope',
        'pair_two_challenge',
        'pair_two_hope',
    )

    def validate(self):
        for field in self.FIELDS:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = 'Please write a slightly longer response.'

    def process(self):
        result = {}
        for field in self.FIELDS:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class InterocepterTool(BaseTool):
    name = 'Interocepter'
    description = (
        'Transform a confusing idea into a clearly understood project by defining its '
        'purpose, importance, ideal outcome, success criteria, and the stakes of acting or not.'
    )
    version = '1.0'

    PHASES = (
        ('creator_and_date',  'Project creator name and date (1 min)'),
        ('project_name',      'Name of the project (1 min)'),
        ('purpose',           'Purpose — what do you want to accomplish? (3 min)'),
        ('importance',        'Importance — what\'s the biggest difference this will make? (3 min)'),
        ('ideal_outcome',     'Ideal Outcome — what does the completed project look like? (3 min)'),
        ('success_criteria',  'Success Criteria — what has to be true when the project is finished? (10 min)'),
        ('best_result',       'Best Result — if you do take action (3 min)'),
        ('worst_result',      'Worst Result — if you don\'t take action (3 min)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 2:
                self.errors[field] = f'{label}: please write a response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result


class GenRelStarTool(BaseTool):
    name = 'Generative Relationships STAR'
    description = (
        'Diagnose how your working group\'s Separateness, Tuning, Action, and Reason to work '
        'together combine to produce the results — or dysfunctions — you experience.'
    )
    version = '1.0'

    PHASES = (
        ('individual_assessment',  'Your individual STAR compass ratings — S, T, A, R (5 min)'),
        ('small_group_consensus',  'Small group consensus placements and key differences noted (5 min)'),
        ('results_type',           'The type of results your group\'s pattern generates (5 min)'),
        ('action_steps',           'Action steps to boost elements needing attention (5 min)'),
        ('first_steps',            'First steps the whole group will take right now (5 min)'),
    )

    def validate(self):
        for field, label in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            if len(value) < 3:
                self.errors[field] = f'{label}: please write a slightly longer response.'

    def process(self):
        result = {}
        for field, _ in self.PHASES:
            value = (self.user_input.get(field) or '').strip()
            result[field] = value
        return result
