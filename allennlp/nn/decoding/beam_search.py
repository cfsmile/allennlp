from collections import defaultdict
from typing import Dict, List

from allennlp.common.registrable import FromParams
from allennlp.nn.decoding.decoder_step import DecoderStep
from allennlp.nn.decoding.decoder_state import DecoderState


class BeamSearch(FromParams):
    """
    This class implements beam search over transition sequences given an initial ``DecoderState``
    and a ``DecoderStep``, returning the highest scoring final states found by the beam (the states
    will keep track of the transition sequence themselves).

    The initial ``DecoderState`` is assumed to be `batched`.  The value we return from the search
    is a dictionary from batch indices to ranked finished states.

    IMPORTANT: We assume that the ``DecoderStep`` that you are using returns possible next states
    in sorted order, so we do not do an additional sort inside of ``BeamSearch.search()``.  If
    you're implementing your own ``DecoderStep``, you must ensure that you've sorted the states
    that you return.
    """
    def __init__(self, beam_size: int) -> None:
        self._beam_size = beam_size

    def search(self,
               num_steps: int,
               initial_state: DecoderState,
               decoder_step: DecoderStep,
               keep_final_unfinished_states: bool = True) -> Dict[int, List[DecoderState]]:
        """
        Parameters
        ----------
        num_steps : ``int``
            How many steps should we take in our search?  This is an upper bound, as it's possible
            for the search to run out of valid actions before hitting this number, or for all
            states on the beam to finish.
        initial_state : ``DecoderState``
            The starting state of our search.  This is assumed to be `batched`, and our beam search
            is batch-aware - we'll keep ``beam_size`` states around for each instance in the batch.
        decoder_step : ``DecoderStep``
            The ``DecoderStep`` object that defines and scores transitions from one state to the
            next.
        keep_final_unfinished_states : ``bool``, optional (default=True)
            If we run out of steps before a state is "finished", should we return that state in our
            search results?

        Returns
        -------
        best_states : ``Dict[int, List[DecoderState]]``
            This is a mapping from batch index to the top states for that instance.
        """
        finished_states: Dict[int, List[DecoderState]] = defaultdict(list)
        states = [initial_state]
        step_num = 1
        while states and step_num <= num_steps:
            next_states: Dict[int, List[DecoderState]] = defaultdict(list)
            grouped_state = states[0].combine_states(states)
            for next_state in decoder_step.take_step(grouped_state, max_actions=self._beam_size):
                # NOTE: we're doing state.batch_indices[0] here (and similar things below),
                # hard-coding a group size of 1.  But, our use of `next_state.is_finished()`
                # already checks for that, as it crashes if the group size is not 1.
                batch_index = next_state.batch_indices[0]
                if next_state.is_finished():
                    finished_states[batch_index].append(next_state)
                else:
                    if step_num == num_steps and keep_final_unfinished_states:
                        finished_states[batch_index].append(next_state)
                    next_states[batch_index].append(next_state)
            states = []
            for batch_index, batch_states in next_states.items():
                # The states from the generator are already sorted, so we can just take the first
                # ones here, without an additional sort.
                states.extend(batch_states[:self._beam_size])
            step_num += 1
        best_states: Dict[int, List[DecoderState]] = {}
        for batch_index, batch_states in finished_states.items():
            # The time this sort takes is pretty negligible, no particular need to optimize this
            # yet.  Maybe with a larger beam size...
            finished_to_sort = [(-state.score[0].item(), state) for state in batch_states]
            finished_to_sort.sort(key=lambda x: x[0])
            best_states[batch_index] = [state[1] for state in finished_to_sort[:self._beam_size]]
        return best_states
