from django.test import SimpleTestCase
from django.urls import reverse


class NewStarterCaseStudyTests(SimpleTestCase):
    def test_landing_page_links_train_new_starter_card_to_case_study(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<a class="use-case-link" href="{reverse("new_starter_case_study")}">',
        )
        self.assertNotContains(response, 'use-case-card--link')

    def test_case_study_is_public_anonymised_and_outcome_led(self):
        response = self.client.get(reverse('new_starter_case_study'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'case_studies/new_starter.html')
        self.assertContains(response, 'first 90-day plan')
        self.assertContains(response, 'Six business functions')
        self.assertContains(response, 'A practical first-90-days agenda')
        self.assertNotContains(response, 'tester@kwacart.local')
        self.assertNotContains(
            response,
            'd2a56868-962f-4b45-b2c1-96d1df670d',
        )


class SuccessionCaseStudyTests(SimpleTestCase):
    def test_landing_page_links_only_case_study_cta(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<a class="use-case-link" href="{reverse("succession_case_study")}">',
        )
        self.assertNotContains(response, 'use-case-card--link')

    def test_case_study_is_public_anonymised_and_action_led(self):
        response = self.client.get(reverse('succession_case_study'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'case_studies/succession.html')
        self.assertContains(response, 'Discovery &amp; Action Dialogue')
        self.assertContains(response, 'Six actions for the next 30 days')
        self.assertContains(response, 'The gap was not talent')
        self.assertNotContains(response, 'tester@kwacart.local')
        self.assertNotContains(
            response,
            '450f58a7-f2a7-49eb-9',
        )


class WinningGrantCaseStudyTests(SimpleTestCase):
    def test_landing_page_links_only_case_study_cta(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<a class="use-case-link" href="{reverse("winning_grant_case_study")}">',
        )
        self.assertNotContains(response, 'use-case-card--link')

    def test_case_study_is_public_anonymised_and_evidence_led(self):
        response = self.client.get(reverse('winning_grant_case_study'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'case_studies/winning_grant.html')
        self.assertContains(response, '25/10 Crowd Sourcing')
        self.assertContains(
            response,
            'A Primary School Environmental Innovation Hub',
        )
        self.assertContains(response, '24/25 · Living laboratory')
        self.assertNotContains(response, 'tester@kwacart.local')
        self.assertNotContains(
            response,
            '23e8dcd5-7188-4103-8fa1-8',
        )


class ServiceTransformationCaseStudyTests(SimpleTestCase):
    def test_landing_page_links_only_case_study_cta(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<a class="use-case-link" href="{reverse("service_transformation_case_study")}">',
        )
        self.assertNotContains(response, 'use-case-card--link')

    def test_case_study_is_public_anonymised_and_system_focused(self):
        response = self.client.get(reverse('service_transformation_case_study'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            'case_studies/service_transformation.html',
        )
        self.assertContains(response, 'Shift &amp; Share')
        self.assertContains(response, '20% of its lifespan')
        self.assertContains(response, 'A six-part service-flow improvement plan')
        self.assertContains(response, 'system-flow problem')
        self.assertNotContains(response, 'tester@kwacart.local')
        self.assertNotContains(response, 'Sarah Patel')
        self.assertNotContains(
            response,
            '0c1fade3-133e-443e-b976-30a2e2',
        )


class OppositionCaseStudyTests(SimpleTestCase):
    def test_landing_page_links_only_case_study_cta(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<a class="use-case-link" href="{reverse("opposition_case_study")}">',
        )
        self.assertNotContains(response, 'use-case-card--link')

    def test_case_study_is_public_anonymised_and_commitment_led(self):
        response = self.client.get(reverse('opposition_case_study'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'case_studies/opposition.html')
        self.assertContains(response, 'Wicked Questions')
        self.assertContains(response, 'Generative Relationships STAR')
        self.assertContains(response, 'Reason</dt><dd>9.2/10')
        self.assertContains(response, 'Six visible commitments')
        self.assertNotContains(response, 'tester@kwacart.local')
        self.assertNotContains(response, 'Sarah Patel')
        self.assertNotContains(response, 'AeroTech')
        self.assertNotContains(
            response,
            'd3a983d4-72dd-4b49-9845-c4851',
        )
        self.assertNotContains(
            response,
            '3cfd39cc-f5aa-4dd4-8e34-996dc3dfe',
        )


class PersonCentredPlanCaseStudyTests(SimpleTestCase):
    def test_landing_page_links_only_case_study_cta(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<a class="use-case-link" href="{reverse("person_centred_plan_case_study")}">',
        )
        self.assertNotContains(response, 'use-case-card--link')

    def test_case_study_is_public_anonymised_and_person_led(self):
        response = self.client.get(reverse('person_centred_plan_case_study'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            'case_studies/person_centred_plan.html',
        )
        self.assertContains(response, 'Conversation Café')
        self.assertContains(response, 'Four goals shaped around the apprentice')
        self.assertContains(response, 'A three-stage communication pathway')
        self.assertContains(response, 'Inclusion is a shared responsibility')
        self.assertNotContains(response, 'tester@kwacart.local')
        self.assertNotContains(response, 'Ted')
        self.assertNotContains(response, 'AeroTech')
        self.assertNotContains(
            response,
            '5843444b-ea64-47a0-8b9c-3779',
        )


class LearningPlanCaseStudyTests(SimpleTestCase):
    def test_landing_page_links_only_case_study_cta(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<a class="use-case-link" href="{reverse("learning_plan_case_study")}">',
        )
        self.assertNotContains(response, 'use-case-card--link')

    def test_case_study_is_public_anonymised_and_learning_focused(self):
        response = self.client.get(reverse('learning_plan_case_study'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'case_studies/learning_plan.html')
        self.assertContains(response, 'What, So What, Now What?')
        self.assertContains(response, 'Six principles for effective workplace learning')
        self.assertContains(response, 'A graduated 12-month learning pathway')
        self.assertContains(response, 'Seven actions for the first 30 days')
        self.assertNotContains(response, 'tester@kwacart.local')
        self.assertNotContains(response, 'Ted')
        self.assertNotContains(response, 'AeroTech')
        self.assertNotContains(
            response,
            '90c0838e-8da8-41a1-9b6d-',
        )


class PositiveBehaviourCaseStudyTests(SimpleTestCase):
    def test_landing_page_links_only_case_study_cta(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<a class="use-case-link" href="{reverse("positive_behaviour_case_study")}">',
        )
        self.assertNotContains(response, 'use-case-card--link')

    def test_case_study_is_public_anonymised_and_non_punitive(self):
        response = self.client.get(reverse('positive_behaviour_case_study'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'case_studies/positive_behaviour.html')
        self.assertContains(response, 'Project Vision Map')
        self.assertContains(response, 'Min Specs')
        self.assertContains(response, 'Eight essential everyday behaviours')
        self.assertContains(response, 'A six-month reflection and inclusion project')
        self.assertNotContains(response, 'tester@kwacart.local')
        self.assertNotContains(response, 'Ted')
        self.assertNotContains(response, 'Sarah Patel')
        self.assertNotContains(
            response,
            '27865f5f-2593-44de-aeda-bc0',
        )
        self.assertNotContains(
            response,
            'acce54fd-70d3-4b66-be27-1a6bbb1f3e0c',
        )


class CommunicationPlanCaseStudyTests(SimpleTestCase):
    def test_landing_page_links_only_case_study_cta(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<a class="use-case-link" href="{reverse("communication_plan_case_study")}">',
        )
        self.assertNotContains(response, 'use-case-card--link')

    def test_case_study_is_public_anonymised_and_outcome_led(self):
        response = self.client.get(reverse('communication_plan_case_study'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'case_studies/communication_plan.html')
        self.assertContains(response, 'Five structures, one communication cycle')
        self.assertContains(response, 'Five minimum conditions for success')
        self.assertContains(response, 'A three-week communication and review plan')
        self.assertContains(response, '10-minute end-of-day review')
        self.assertNotContains(response, 'tester@kwacart.local')
        self.assertNotContains(response, 'Juniata')
        self.assertNotContains(response, 'Ted')