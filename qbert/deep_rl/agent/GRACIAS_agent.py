#######################################################################
# Copyright (C) 2017 Shangtong Zhang(zhangshangtong.cpp@gmail.com)    #
# Permission given to modify the code as long as you keep this        #
# declaration at the top                                              #
#######################################################################

from ..network import *
from ..component import *
from .BaseAgent import *
import torchvision
from .DQN_module import *
from .rewardFunctions import *

class GRACIAS(BaseAgent):
    def __init__(self, config, moduleConfig):
        BaseAgent.__init__(self, config)
        self.moduleConfig = moduleConfig
        self.config = config
        self.numModules = 4
        self.modules = [DQNModule(self.moduleConfig) for i in range(self.numModules)]

        self.task = config.task_fn()
        self.network = config.network_fn(self.task.state_dim, 4)
        self.target_network = config.network_fn(self.task.state_dim, 4)
        self.target_network.load_state_dict(self.network.state_dict())
        self.replay = config.replay_fn()
        self.random_process = config.random_process_fn(4)
        self.total_steps = 0

    def get_final_action(self, action, state):
        finalQValues = action[0] * self.modules[0].get_q_values(state) + action[1] * self.modules[1].get_q_values(state) + action[2] * self.modules[2].get_q_values(state) + action[3] * self.modules[3].get_q_values(state)
        return np.argmax(finalQValues)


    def soft_update(self, target, src):
        for target_param, param in zip(target.parameters(), src.parameters()):
            target_param.detach_()
            target_param.copy_(target_param * (1.0 - self.config.target_network_mix) +
                                    param * self.config.target_network_mix)

    def evaluation_action(self, state):
        self.config.state_normalizer.set_read_only()
        state = np.stack([self.config.state_normalizer(state)])
        action = self.network.predict(state, to_numpy=True).flatten()
        self.config.state_normalizer.unset_read_only()
        return action

    def episode(self, deterministic=False):
        self.random_process.reset_states()
        state = self.task.reset()
        state = self.config.state_normalizer(state)

        config = self.config

        steps = 0
        total_reward = 0.0
        while True:

            action = self.network.predict(np.stack([state]), True).flatten()
            if not deterministic:
                action += self.random_process.sample()
            atariAction = self.get_final_action(action, state)
            next_state, reward, done, info = self.task.step(atariAction)
            next_state = self.config.state_normalizer(next_state)
            total_reward += reward
            reward = self.config.reward_normalizer(reward)

            if not deterministic:
                self.replay.feed([state, action, reward, next_state, int(done)])
                self.modules[0].update(state, atariAction, change_reward0(reward), next_state, done, deterministic)
                self.modules[1].update(state, atariAction, change_reward1(reward), next_state, done, deterministic)
                self.modules[2].update(state, atariAction, change_reward2(reward), next_state, done, deterministic)
                self.modules[3].update(state, atariAction, change_reward3(reward, done), next_state, done, deterministic)
                self.total_steps += 1

            steps += 1
            state = next_state

            if not deterministic and self.replay.size() >= config.min_memory_size:
                experiences = self.replay.sample()
                states, actions, rewards, next_states, terminals = experiences

                phi_next = self.target_network.feature(next_states)
                a_next = self.target_network.actor(phi_next)
                q_next = self.target_network.critic(phi_next, a_next)
                terminals = tensor(terminals).unsqueeze(1)
                rewards = tensor(rewards).unsqueeze(1)
                q_next = config.discount * q_next * (1 - terminals)
                q_next.add_(rewards)
                q_next = q_next.detach()
                phi = self.network.feature(states)
                q = self.network.critic(phi, tensor(actions))
                critic_loss = (q - q_next).pow(2).mul(0.5).sum(-1).mean()

                self.network.zero_grad()
                critic_loss.backward()
                self.network.critic_opt.step()

                phi = self.network.feature(states)
                action = self.network.actor(phi)
                policy_loss = -self.network.critic(phi.detach(), action).mean()

                self.network.zero_grad()
                policy_loss.backward()
                self.network.actor_opt.step()

                self.soft_update(self.target_network, self.network)

            if done:
                break

        return total_reward, steps
