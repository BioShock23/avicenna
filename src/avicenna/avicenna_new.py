from typing import Iterable, Set, Optional, List
from pathlib import Path

from avicenna.debug import InputFeatureDebugger, HypothesisInputFeatureDebugger
from fuzzingbook.Grammars import Grammar, is_valid_grammar
from debugging_framework.types import OracleType

from avicenna.input.input import Input
from avicenna.learning.learner import CandidateLearner
from avicenna.learning.table import Candidate
from avicenna.learning.exhaustive import ExhaustivePatternCandidateLearner
from avicenna.generator.generator import Generator, ISLaGrammarBasedGenerator
from avicenna.runner.execution_handler import ExecutionHandler
from avicenna.learning.reducer import (
    FeatureReducer,
    SHAPRelevanceLearner,
    GradientBoostingTreeRelevanceLearner,
)
from avicenna.features.feature_collector import GrammarFeatureCollector
from avicenna.logger import log_execution


class Avicenna(HypothesisInputFeatureDebugger):
    """
    Avicenna is a hypothesis-based input feature debugger that uses a pattern-based candidate learner to explain the input
    features that result in the failure of a program.
    """

    def __init__(
        self,
        grammar: Grammar,
        oracle: OracleType,
        initial_inputs: Iterable[Input],
        max_iterations: int = 10,
        timeout_seconds: int = 3600,
        top_n_relevant_features: int = 3,
        learner: CandidateLearner = None,
        pattern_file: Path = None,
        min_recall: float = 0.9,
        min_specificity: float = 0.6,
        generator: Generator = None,
        runner: ExecutionHandler = None,
    ):
        learner_parameter = {
            "grammar": grammar,
            "pattern_file": pattern_file,
            "min_recall": min_recall,
            "min_specificity": min_specificity,
        }
        learner = (
            learner
            if learner
            else ExhaustivePatternCandidateLearner(**learner_parameter)
        )
        generator = generator if generator else ISLaGrammarBasedGenerator(grammar)

        super().__init__(
            grammar,
            oracle,
            initial_inputs,
            learner=learner,
            generator=generator,
            runner=runner,
            timeout_seconds=timeout_seconds,
            max_iterations=max_iterations,
        )
        self.top_n_relevant_features = top_n_relevant_features

        self.feature_learner: FeatureReducer = SHAPRelevanceLearner(
            self.grammar,
            top_n_relevant_features=self.top_n_relevant_features,
            classifier_type=GradientBoostingTreeRelevanceLearner,
        )
        self.collector = GrammarFeatureCollector(self.grammar)

    def set_feature_reducer(self, feature_reducer: FeatureReducer):
        """
        Set the feature learner to reduce the input features.
        """
        self.feature_learner = feature_reducer

    def assign_test_inputs_features(self, test_inputs: Set[Input]) -> Set[Input]:
        """
        Assign the features to the test inputs using the feature collector.
        """
        for inp in test_inputs:
            if not inp.features:
                inp.features = self.collector.collect_features(inp)
        return test_inputs

    def get_irrelevant_features(self, test_inputs: Set[Input]) -> Set[str]:
        """
        Get the irrelevant features based on the test inputs.
        """
        test_inputs = self.assign_test_inputs_features(test_inputs)
        relevant_features = self.feature_learner.learn(test_inputs)
        relevant_feature_non_terminals = {
            feature.non_terminal for feature in relevant_features
        }

        irrelevant_features = set(self.grammar.keys()).difference(
            relevant_feature_non_terminals
        )
        return irrelevant_features

    @log_execution
    def learn_candidates(self, test_inputs: Set[Input]) -> Optional[List[Candidate]]:
        """
        Learn the candidates based on the test inputs.
        :param test_inputs: The test inputs to learn the candidates from.
        :return Optional[List[Candidate]]: The learned candidates.
        """
        irrelevant_features = self.get_irrelevant_features(test_inputs)
        candidates = self.learner.learn_candidates(
            test_inputs, exclude_nonterminals=irrelevant_features
        )
        return candidates

    @log_execution
    def generate_test_inputs(self, candidates: List[Candidate]) -> Set[Input]:
        """
        Generate the test inputs based on the learned candidates.
        :param candidates: The learned candidates.
        :return Set[Input]: The generated test inputs.
        """
        test_inputs = self.generator.generate_test_inputs(candidates=candidates)
        return test_inputs

    @log_execution
    def run_test_inputs(self, test_inputs: Set[Input]) -> Set[Input]:
        """
        Run the test inputs to label them. The test inputs are labeled based on the oracle.
        Feature vectors are assigned to the test inputs.
        :param test_inputs: The test inputs to run.
        :return Set[Input]: The labeled test inputs.
        """
        labeled_test_inputs = self.runner.label(test_inputs=test_inputs)
        feature_test_inputs = self.assign_test_inputs_features(labeled_test_inputs)
        return feature_test_inputs
