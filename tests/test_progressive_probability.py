import unittest

from fatfish_core.progressive_probability import MissCounters, progressive_probability


class ProgressiveProbabilityTests(unittest.TestCase):
    def test_linear_increase_and_cap(self):
        self.assertAlmostEqual(progressive_probability(.1,.02,3,ceiling=.3),.16)
        self.assertEqual(progressive_probability(.1,.02,100,ceiling=.3),.3)
        self.assertEqual(progressive_probability(0,.02,1,ceiling=.3),.02)
        self.assertEqual(progressive_probability(0,0,100),0)

    def test_invalid_probabilities_are_not_silently_accepted(self):
        for base,step,cap in ((float('nan'),0,1),(.1,-.1,1),(.1,.1,2)):
            with self.assertRaises(ValueError):progressive_probability(base,step,1,ceiling=cap)

    def test_channels_and_full_conversations_are_independent_and_bounded(self):
        counts=MissCounters(limit=3)
        first=('voice','napcat:GroupMessage:1');second=('meme','napcat:GroupMessage:1')
        counts.record(first,sent=False);counts.record(first,sent=False)
        counts.record(second,sent=False)
        self.assertEqual(counts.get(first),2);self.assertEqual(counts.get(second),1)
        self.assertEqual(counts.get(('voice','napcat:FriendMessage:1')),0)
        self.assertEqual(counts.get(('voice','other:GroupMessage:1')),0)
        counts.record(first,sent=True);self.assertEqual(counts.get(first),0)
        counts.record('third',sent=False);counts.record('fourth',sent=False)
        self.assertLessEqual(len(counts.counts),3)
