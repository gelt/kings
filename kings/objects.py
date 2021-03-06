import os
from copy import deepcopy
from glob import glob

import gevent
import pkg_resources
import yaml
from gevent.queue import Queue

from .common import *

class ObjectNotFound(Exception): pass
class LocationNotFound(ObjectNotFound): pass


class Db(object):
    _instance = None

    @classmethod
    def init(cls, config):
        obj_db = cls(config.get('kings', 'content_path'))
        cls._instance = obj_db
        obj_db.reload()
        return obj_db

    @classmethod
    def instance(cls):
        assert cls._instance
        return cls._instance

    def __init__(self, content_path, objects=None):
        self.content_path = content_path
        self.objects = objects or {}

    def __contains__(self, oid):
        return oid in self.objects

    def reload(self):
        for filename in pkg_resources.resource_listdir('kings', self.content_path):
            self.from_yaml(filename=filename)

    def from_yaml(self, oid=None, filename=None):
        assert oid or filename and not (oid and filename)
        if oid:
            filename = "{0}.yaml".format(oid)
        filename = os.path.join(self.content_path, filename)
        data = yaml.load(pkg_resources.resource_stream('kings', filename))
        cls = globals()[data['type']]
        return cls.init(**data)

    def add(self, obj):
        assert obj.oid
        self.objects[obj.oid] = obj

    def remove(self, obj):
        try:
            del self.objects[obj.oid]
        except KeyError:
            raise ObjectNotFound(obj.oid)

    def get(self, oid):
        try:
            return self.objects[oid]
        except KeyError:
            raise ObjectNotFound(oid)

    def query(self, **kwargs):
        objs = []
        for obj in self.objects.values():
            for key, val in kwargs.items():
                if getattr(obj, key) != val:
                    break
            else:
                objs.append(obj)

        return objs


class Object(object):
    instance_counter = 0

    @classmethod
    def init(cls, **kwargs):
        obj = cls(**kwargs)
        Db.instance().add(obj)
        return obj

    @classmethod
    def clone(cls, oid):
        db = Db.instance()
        try:
            prototype = db.get(oid)
        except ObjectNotFound:
            prototype = db.from_yaml(oid=oid)
        cloned = deepcopy(prototype)

        # Make sure that the cone has a unique oid
        cls.instance_counter += 1
        instance_num = cls.instance_counter
        cloned._oid = "{0}:{1}".format(cloned.oid, instance_num)

        db.add(cloned)
        return cloned

    def __init__(self, oid=None, short_desc=None, long_desc=None, location_oid=None, **kwargs):
        self._oid = oid
        self._short_desc = short_desc
        self._long_desc = long_desc
        self._location_oid = location_oid

    def __repr__(self):
        return '{0}(**{1})'.format(self.__class__.__name__, self.__dict__)

    def __ror__(self, action):
        ''' We define the | (pipe) operator as "send message to"
        '''
        if hasattr(self, 'actions'):
            self.actions.put(action)

    def __eq__(self, other):
        return self.oid == other.oid

    @property
    def oid(self):
        return self._oid

    @property
    def long_desc(self):
        return self._long_desc

    @property
    def short_desc(self):
        return self._short_desc

    @property
    def location_oid(self):
        return self._location_oid

    @location_oid.setter
    def location_oid(self, val):
        try:
            location = Db.instance().get(oid=val)
        except ObjectNotFound:
            raise LocationNotFound(val)
        else:
            self._location_oid = val

    def location(self):
        if self.location_oid:
            try:
                return Db.instance().get(self.location_oid)
            except ObjectNotFound:
                log.warn("No location found for oid {0}".format(self.location_oid))
                return None
        else:
            return None

    def move_to(self, target_oid):
        if target_oid in Db.instance():
            self._location_oid = target_oid
        else:
            raise LocationNotFound(target_oid)

    def killable(self, by):
        return False


class Action(object):
    def __init__(self, *args, **kwargs):
        pass

    def execute(self):
        raise NotImplementedError()

class MessageAction(Action):
    def __init__(self, message):
        self.message = message

    def execute(self):
        return self.message

class LookAction(Action):
    def __init__(self, observer, to_observe):
        self.observer = observer
        self.to_observe = to_observe

    def execute(self):
        try:
            if self.observer.location_oid == self.to_observe:
                obj = Db.instance().get(self.to_observe)
            else:
                obj = Db.instance().query(oid=self.to_observe, location_oid=self.observer.location_oid)[0]

            output = [obj.long_desc]
            if hasattr(obj, "exits"):
                if obj.exits:
                    exits = "Exits: {0}".format(", ".join(sorted(obj.exits.keys())))
                else:
                    exits = "There are no obvious exists"
                output.append(exits)

                things = Db.instance().query(location_oid=self.observer.location_oid)
                if things:
                    output.extend([t.short_desc for t in things if t.oid != self.observer.oid])

            return "\n".join(output)
        except ObjectNotFound:
            return "There's no \"{0}\" here.".format(self.to_observe)

class MoveAction(Action):
    def __init__(self, mover, destination_oid):
        self.mover = mover
        self.destination_oid = destination_oid

    def execute(self):
        try:
            self.mover.location_oid = self.destination_oid
        except LocationNotFound:
            return 'Oops, could not find "{0}"'.format(self.destination_oid)
        else:
            return LookAction(self.mover, self.destination_oid).execute()

class SayAction(Action):
    def __init__(self, sayer, message):
        self.sayer = sayer
        self.message = message

    def execute(self):
        location = self.sayer.location()

        for obj in location.contents():
            if obj != self.sayer:
                '{0} says: "{1}"'.format(self.sayer.oid, self.message) | obj

        return 'You say: "{0}"'.format(self.message)

class KillAction(Action):
    def __init__(self, attacker, target):
        self.attacker = attacker
        self.target = target

    def execute(self):
        location = self.attacker.location()
        try:
            target = Db.instance().query(oid=self.target, location_oid=location.oid)[0]
        except (ObjectNotFound, IndexError):
            return 'There is no "{0}" here'.format(self.target)
        else:
            for obj in location.contents():
                if obj != self.attacker:
                    '{0} starts to fight {1}'.format(self.attacker.oid, target.oid) | obj

            self.attacker.attack(target)
            target.attack(self.attacker)

            return 'You start to fight {0}'.format(target.oid)

class AttackAction(Action):
    def __init__(self, attacker, target):
        self.attacker = attacker
        self.target = target

    def execute(self):
        if self.attacker.location_oid == self.target.location_oid:
            damage = 1
            self.target.hp -= damage
            if self.target.hp < 0:
                return "You have died."
            else:
                greenlet = gevent.Greenlet(self.requeue)
                greenlet.start_later(2)
                return "{0} hit you for {1}hp ({2}hp left).".format(self.attacker.oid, damage, self.target.hp)
        else:
            return "{0} stopped attacking you.".format(self.attacker.oid)

    def requeue(self):
        self.attacker.attack(self.target)

class ExitAction(Action):
    def __init__(self, to_exit, message):
        self.to_exit = to_exit
        self.message = message

    def execute(self):
        self.to_exit.running = False
        return self.message

class Player(Object):
    @classmethod
    def init(cls, **kwargs):
        kwargs['running'] = True
        player = super(Player, cls).init(**kwargs)
        LookAction(player, player.location_oid) | player 
        return player

    def __init__(self, running=False, **kwargs):
        super(Player, self).__init__(**kwargs)
        self.running = running
        self.prompt = "\n% "
        self.hp = 20
        self.actions = Queue()

    @property
    def short_desc(self):
        return self.oid

    def interpret(self, line):
        sep = " "
        verb, sep, rest = line.partition(sep)
        action = None

        if verb == "ls":
            action = repr(Db.instance().objects)
        elif verb == "look":
            if rest:
                action = LookAction(rest)
            else:
                action = LookAction(self, self.location_oid)
        elif verb == "exit":
            action = ExitAction(self, "Goodbye")
        elif verb == "say":
            action = SayAction(self, rest)
        elif verb == "kill":
            action = KillAction(self, rest)
        else:
            room = self.location()
            exits = room.exits
            if verb in exits:
                action = MoveAction(self, exits[verb])

        if action is None:
            return 'I don\'t know what "{0}" means'.format(verb)
        return action

    def attack(self, target):
        AttackAction(self, target) | target

    def close(self):
        Db.instance().remove(self)

class Npc(Object):
    def __init__(self, **kwargs):
        super(Npc, self).__init__(**kwargs)
        self.hp = 5

    def attack(self, target):
        AttackAction(self, target) | target

    def killable(self, by):
        return self.location_oid == by.location_oid

class Location(Object):
    def __init__(self, exits=None, npcs=None, **kwargs):
        super(Location, self).__init__(**kwargs)
        self._exits = exits or {}
        for npc_oid in npcs or []:
            cloned = Npc.clone(npc_oid)
            cloned._location_oid = self.oid

    @property
    def exits(self):
        return self._exits

    def contents(self):
        return Db.instance().query(location_oid=self.oid)

